"""
Immich Live Photo Linker Script

Features:
- Identifies unlinked Live Photo/Video pairs via the Immich API
- Interactive confirmation prompts
- Audit trail CSVs
- Dry run mode

Usage:
1. Configure API settings in the `config.yaml` file
2. Run: `python link_livephoto_videos.py [flags]`

Safety:
- Always test with `--dry-run` first.
"""

import json
import re
import requests
import pandas as pd

import os
from datetime import datetime
from utils import (
    get_api_headers,
    get_confirmation,
    load_config,
    parse_link_args,
    search_assets,
)


def get_unlinked_livephoto_ids(api_config: dict) -> pd.DataFrame:
    """Identify unlinked Live Photo assets using the Immich API.

    Uses POST /api/search/metadata to fetch all VIDEO and IMAGE assets,
    then matches them by base filename and creation timestamp.

    Args:
        api_config: Dictionary containing Immich API endpoint and credentials.

    Returns:
        DataFrame containing photo-video asset pairs needing linkage.
    """
    # 1. Fetch all video assets
    print("  Fetching video assets...")
    video_assets = search_assets(api_config, {"type": "VIDEO"})

    if not video_assets:
        print("No video assets identified. Ending script.")
        quit()

    video_assets_df = pd.DataFrame(
        [
            {
                "video_asset_id": a["id"],
                "video_filename": a["originalFileName"],
                "video_filedate": a["fileCreatedAt"],
            }
            for a in video_assets
        ]
    )

    # Extract base filenames from videos (strip extension and trailing _N suffix)
    video_assets_df["photo_basefilename"] = (
        video_assets_df["video_filename"]
        .str.replace(r"\.[^.]+$", "", regex=True)
        .str.replace(r"\_\d$", "", regex=True)
    )

    # 2. Fetch all image assets
    print("  Fetching image assets...")
    image_assets = search_assets(api_config, {"type": "IMAGE"})

    # Filter to only unlinked images (no livePhotoVideoId)
    unlinked_images = [a for a in image_assets if not a.get("livePhotoVideoId")]

    if not unlinked_images:
        print("No unlinked image assets identified. Ending script.")
        quit()

    unlinked_photo_assets_df = pd.DataFrame(
        [
            {
                "photo_asset_id": a["id"],
                "photo_filename": a["originalFileName"],
                "photo_filedate": a["fileCreatedAt"],
            }
            for a in unlinked_images
        ]
    )

    # Extract base filenames from photos (strip extension)
    unlinked_photo_assets_df["photo_basefilename"] = unlinked_photo_assets_df[
        "photo_filename"
    ].str.replace(r"\.[^.]+$", "", regex=True)

    # 3. Match photos to videos by base filename
    unlinked_photo_assets_df = unlinked_photo_assets_df.merge(
        video_assets_df, on="photo_basefilename", how="inner"
    )

    if unlinked_photo_assets_df.empty:
        print("No unlinked Live Photos identified. Ending script.")
        quit()

    # 3.1 Remove photos with duplicate base filenames (ambiguous matches)
    duplicate_basenames = (
        unlinked_photo_assets_df.groupby("photo_basefilename")
        .filter(lambda x: len(x) > 1)["photo_basefilename"]
        .unique()
    )
    if len(duplicate_basenames) > 0:
        unlinked_photo_assets_df = unlinked_photo_assets_df[
            ~unlinked_photo_assets_df["photo_basefilename"].isin(duplicate_basenames)
        ]

    if unlinked_photo_assets_df.empty:
        print("No unlinked Live Photos identified. Ending script.")
        quit()

    # 3.2 Filter by matching timestamps (within 3 seconds)
    unlinked_photo_assets_df["photo_dt"] = pd.to_datetime(
        unlinked_photo_assets_df["photo_filedate"], utc=True
    )
    unlinked_photo_assets_df["video_dt"] = pd.to_datetime(
        unlinked_photo_assets_df["video_filedate"], utc=True
    )

    unlinked_photo_assets_df["time_diff"] = (
        (unlinked_photo_assets_df["photo_dt"] - unlinked_photo_assets_df["video_dt"])
        .dt.total_seconds()
        .abs()
    )
    MAX_TIME_DIFF = 3  # seconds
    unlinked_photo_assets_df = unlinked_photo_assets_df[
        unlinked_photo_assets_df["time_diff"] <= MAX_TIME_DIFF
    ]

    unlinked_photo_assets_df = unlinked_photo_assets_df.drop(
        ["photo_dt", "video_dt", "time_diff"], axis=1
    ).reset_index(drop=True)

    if unlinked_photo_assets_df.empty:
        print("No unlinked Live Photos identified. Ending script.")
        quit()

    return unlinked_photo_assets_df


def print_example_unlinked_photo(asset: pd.Series, api_config: dict):
    """Prints example information for a single unlinked Live Photo.

    Args:
        asset: Series containing a single asset example.
        api_config: Dictionary containing Immich API endpoint and credentials.
    """
    headers = get_api_headers(api_config)

    def get_asset_info(asset_id: str) -> dict:
        url = f"{api_config['url']}/api/assets/{asset_id}"
        result = requests.get(url=url, headers=headers)
        result.raise_for_status()
        return result.json()

    live_photo_info = get_asset_info(asset["photo_asset_id"])
    live_video_info = get_asset_info(asset["video_asset_id"])

    example_file_info = f"""Example Unlinked Live Photo/Video File Information:
    - Live Photo Original Filename: {live_photo_info["originalFileName"]}
    - Live Photo Creation Date: {live_photo_info["fileCreatedAt"]}
    - Live Video Original Filename: {live_video_info["originalFileName"]}
    - Live Video Creation Date: {live_video_info["fileCreatedAt"]}"""

    print(example_file_info)


def link_livephoto_assets(unlinked_livephoto_df: pd.DataFrame, api_config: dict):
    """Update Immich assets through API to establish Live Photo links.

    Uses PUT /api/assets/{id} to set livePhotoVideoId on each photo asset.

    Args:
        unlinked_livephoto_df: DataFrame containing asset pairs to link.
        api_config: Dictionary containing Immich API endpoint and credentials.

    Raises:
        RuntimeError: If API requests fail persistently.
    """
    failed_updates = []
    successful_updates = 0
    headers = get_api_headers(api_config, content_type=True)

    for i, asset in unlinked_livephoto_df.iterrows():
        print(f"Merging asset: {i + 1}/{unlinked_livephoto_df.shape[0]}", end="\r")

        url = f"{api_config['url']}/api/assets/{asset['photo_asset_id']}"
        payload = {"livePhotoVideoId": asset["video_asset_id"]}

        result = requests.put(url=url, headers=headers, json=payload)

        if result.status_code == 200:
            successful_updates += 1
        else:
            error_detail = result.json()
            error_msg = f"{error_detail.get('error', 'Unknown error')}: {error_detail.get('message', 'No message provided')}"

            failed_updates.append(
                {
                    "photo_asset_id": asset["photo_asset_id"],
                    "photo_filename": asset["photo_filename"],
                    "photo_filedate": asset["photo_filedate"],
                    "video_asset_id": asset["video_asset_id"],
                    "video_filename": asset["video_filename"],
                    "video_filedate": asset["video_filedate"],
                    "error_status": result.status_code,
                    "error_message": error_msg,
                }
            )

    print("\nUpdate Summary:")
    print(f"Successfully linked {successful_updates} files.")

    if failed_updates:
        timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
        out_failed_file = f"failed_updates_{timestamp}.csv"

        failed_df = pd.DataFrame(failed_updates)
        failed_df = failed_df[
            [
                "photo_asset_id",
                "photo_filename",
                "photo_filedate",
                "video_asset_id",
                "video_filename",
                "video_filedate",
                "error_status",
                "error_message",
            ]
        ]
        failed_df.to_csv(out_failed_file, index=False)

        raise RuntimeError(
            f"Failed to update {len(failed_updates)} files. See {out_failed_file} for details."
        )


def save_asset_record(
    df: pd.DataFrame,
    output_dir: str = "output",
    is_test: bool = False,
    is_dry: bool = False,
):
    """Save identified assets to CSV file in the specified output directory.

    Args:
        df: DataFrame containing assets to save.
        output_dir: Directory where files will be saved (created if it doesn't exist).
        is_test: Whether this is a test run.
        is_dry: Whether this is a dry run.

    Returns:
        str: Path to saved file.
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    if is_test:
        filename = f"TEST_RUN_linked_asset_{timestamp}.csv"
    elif is_dry:
        filename = f"DRY_RUN_linked_asset_{timestamp}.csv"
    else:
        filename = f"linked_assets_{timestamp}.csv"

    out_file = os.path.join(output_dir, filename)
    df.to_csv(out_file, index=False)
    print(f"Record of identified Live Photo/Video assets saved to: {out_file}")
    return out_file


def repair_live_photos(
    api_config: dict,
    dry_run: bool = False,
    test_run: bool = False,
):
    """Main workflow to identify and link unlinked Live Photo/Video pairs.

    Args:
        api_config: Dictionary containing Immich API endpoint and credentials.
        dry_run: If True, only identify and report without making changes.
        test_run: If True, process only one asset as a test.
    """
    print("1/2: Identifying unlinked Live Photo assets...")
    unlinked_photo_assets_df = get_unlinked_livephoto_ids(api_config=api_config)
    print(f"Identified {unlinked_photo_assets_df.shape[0]} unlinked Live Photos.")
    print_example_unlinked_photo(
        asset=unlinked_photo_assets_df.iloc[0], api_config=api_config
    )

    if dry_run:
        confirm_dryrun_save = get_confirmation(
            "Would you like to save a record of the assets? [y/n] "
        )

        if confirm_dryrun_save:
            save_asset_record(unlinked_photo_assets_df, is_dry=True)

        print("Dry run of Live Photo linking completed.")
        return

    if test_run:
        print("\n============= TEST RUN ACTIVE ============\n")
        print("Processing only the first asset as a test.")
        print("==========================================\n")
        unlinked_photo_assets_df = unlinked_photo_assets_df.head(1)

    confirm_link = get_confirmation(
        f"Would you like to link the asset{'s' if unlinked_photo_assets_df.shape[0] > 1 else ''}? [y/n] "
    )
    if not confirm_link:
        print("Live Photo linking cancelled.")
        return

    print("\n2/2: Linking Live Photos and Live Video assets...")
    save_asset_record(unlinked_photo_assets_df, is_test=test_run)
    link_livephoto_assets(
        unlinked_livephoto_df=unlinked_photo_assets_df, api_config=api_config
    )

    print("Live Photos linking complete!")


if __name__ == "__main__":
    # ================================================
    # ⚠️ BEFORE RUNNING: ⚠️
    # Run the script with `--dry-run` and `--test-run` for testing
    # ================================================
    args = parse_link_args()
    config = load_config(args.config)

    repair_live_photos(
        api_config=config["api"],
        dry_run=args.dry_run,
        test_run=args.test_run,
    )
