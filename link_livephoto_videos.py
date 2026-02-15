"""
Immich Live Photo Linker Script

Features:
- Identifies unlinked Live Photo/Video pairs
- Interactive confirmation prompts
- Audit trail CSVs
- Dry run mode

Usage:
1. Configure API and DB settings in the `config.yaml` file
2. Run: `python link_livephoto_videos.py [flags]`

Safety:
- Back up your database before running.
- Always test with `--dry-run` first.
"""

import json
import requests
import psycopg2
import pandas as pd

import os
from datetime import datetime
from utils import get_confirmation, load_config, parse_link_args


def get_unlinked_livephoto_ids(db_config: dict, user_config: dict) -> pd.DataFrame:
    """Identify unlinked Live Photo assets in Immich database.

    Args:
        live_video_suffix: File suffix pattern for video assets (e.g. '_3.mov')
        db_config: Dictionary containing PostgreSQL connection parameters

    Returns:
        DataFrame containing photo-video asset pairs needing linkage

    Raises:
        ConnectionError: If database connection fails.
    """
    unlinked_photo_assets_df = pd.DataFrame()

    # Identify all unlinked photo IDs.
    # Three step process
    # 1. Get all video filenames
    # 2. Get all photo filenames with identical *base* names as the videos.
    #   - e.g., Photo File: "IMG_1234.heic"; Video File: "IMG_1234.MOV"
    # 3. Filter out problematic photo file candidates:
    #   - Duplicated photos
    #   - Photo/Video files with identical filenames but mismatched timestamps.
    with psycopg2.connect(**db_config) as conn:
        with conn.cursor() as cur:
            # 0. Get user name
            cur.execute(
                """
                SELECT id FROM user WHERE name = %s
                """,
                (user_config["name"],),
            )

            user_id = cur.fetchone()
            if not user_id:
                raise ValueError(f"User '{user_config['name']}' not found")

            # 1. Get all live video assets
            cur.execute(
                r"""
                SELECT id, "originalFileName", "fileCreatedAt"
                FROM asset 
                WHERE "ownerId" = %s
                AND lower("originalFileName") ~ '\.(mov|mp4)$';
                """,
                user_id,
            )
            video_assets = cur.fetchall()
            video_assets_df = pd.DataFrame(
                video_assets,
                columns=["video_asset_id", "video_filename", "video_filedate"],
            )

            if video_assets_df.empty:
                print("No video assets identified. Ending script.")
                quit()

            video_assets_df["photo_basefilename"] = (
                video_assets_df["video_filename"]
                .str.replace(r"\.[^.]+$", "", regex=True)
                .str.replace(r"\_\d$", "", regex=True)
            )

            # 2. Get all live photo assets that are missing livePhotoVideoId's.
            photo_basefilename = tuple(video_assets_df["photo_basefilename"].tolist())
            cur.execute(
                r"""
                SELECT id, "originalFileName", "fileCreatedAt"
                FROM asset
                WHERE "ownerId" = %s
                AND "livePhotoVideoId" IS NULL
                AND lower("originalFileName") !~ '\.(mov|mp4)$'
                AND regexp_replace("originalFileName", '\..*$', '') IN %s;
                """,
                (user_id, photo_basefilename),
            )

            unlinked_photo_assets = cur.fetchall()
            unlinked_photo_assets_df = pd.DataFrame(
                unlinked_photo_assets,
                columns=["photo_asset_id", "photo_filename", "photo_filedate"],
            )

            unlinked_photo_assets_df["photo_basefilename"] = unlinked_photo_assets_df[
                "photo_filename"
            ].str.replace(r"\.[^.]+$", "", regex=True)
            unlinked_photo_assets_df = unlinked_photo_assets_df.merge(
                video_assets_df, on="photo_basefilename", how="left"
            )

            if unlinked_photo_assets_df["video_asset_id"].isna().any():
                print("Warning: Some photos could not be matched to video assets!")
                o_nfile = unlinked_photo_assets_df.shape[0]
                unlinked_photo_assets_df = unlinked_photo_assets_df.dropna(
                    subset=["video_asset_id"]
                )
                print(
                    f"Removed {o_nfile - unlinked_photo_assets_df.shape[0]} unlinked assets with missing video files."
                )

            # 3.1 Remove duplicated ids (based on the *base* filename)
            candidate_base_filenames = tuple(
                unlinked_photo_assets_df["photo_basefilename"].tolist()
            )
            cur.execute(
                r"""
                WITH assets_with_base AS (
                    SELECT
                        id,
                        "originalFileName",
                        "ownerId",
                        regexp_replace("originalFileName", '\..*$', '') AS base_filename
                    FROM asset
                    WHERE "ownerId" = %s
                    AND lower("originalFileName") !~ '\.(mov|mp4)$'  -- exclude video files
                )
                SELECT base_filename
                FROM assets_with_base
                GROUP BY base_filename
                HAVING COUNT(*) > 1
                AND base_filename in %s;
                """,
                (user_id, candidate_base_filenames),
            )

            duplicate_files = [row[0] for row in cur.fetchall()]
            if duplicate_files:
                unlinked_photo_assets_df = unlinked_photo_assets_df[
                    ~unlinked_photo_assets_df["photo_basefilename"].isin(
                        duplicate_files
                    )
                ]

            # Merge the video asset df to the unlinked photo df
            if unlinked_photo_assets_df.empty:
                print("No unlinked Live Photos identified. Ending script.")
                quit()

    # 3.2 Filter the unlinked photo assets df to only include photo/video files
    # with a matching time stamp within 3 seconds.
    # This is because sometimes video/photo filenames can be reused over time.
    unlinked_photo_assets_df["photo_dt"] = pd.to_datetime(
        unlinked_photo_assets_df["photo_filedate"], utc=True
    )
    unlinked_photo_assets_df["video_dt"] = pd.to_datetime(
        unlinked_photo_assets_df["video_filedate"], utc=True
    )

    # Calculate time difference in seconds
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
    ).reset_index()

    if unlinked_photo_assets_df.empty:
        print("No unlinked Live Photos identified. Ending script.")
        quit()

    return unlinked_photo_assets_df


def print_example_unlinked_photo(asset: pd.DataFrame, api_config: dict):
    """Prints example information for a single unlinked Live Photo.

    Args:
        asset: DataFrame containing a single asset example.
        api_config: Dictionary containing Immich API endpoint and credentials.
    """

    def get_asset_info(id):
        url = f"{api_config['url']}/api/assets/{asset[id]}"
        payload = {}
        headers = {
            "Accept": "application/json",
            "x-api-key": api_config["api-key"],
        }

        result = requests.request("GET", url=url, headers=headers, data=payload)
        return result.json()

    live_photo_info = get_asset_info("photo_asset_id")
    live_video_info = get_asset_info("video_asset_id")

    example_file_info = f"""Example Unlinked Live Photo/Video File Information:
    - Live Photo Original Filename: {live_photo_info["originalFileName"]}
    - Live Photo Creation Date: {live_photo_info["fileCreatedAt"]}
    - Live Video Original Filename: {live_video_info["originalFileName"]}
    - Live Video Creation Date: {live_video_info["fileCreatedAt"]}"""

    print(example_file_info)

    return


def link_livephoto_assets(unlinked_livephoto_df: pd.DataFrame, api_config: dict):
    """Update Immich assets through API to establish Live Photo links.

    Args:
        unlinked_livephoto_df: DataFrame containing asset pairs to link
        api_config: Dictionary containing Immich API endpoint and credentials

    Raises:
        RuntimeError: If API requests fail persistently
    """
    failed_updates = []
    successful_updates = 0
    for i, asset in unlinked_livephoto_df.iterrows():
        print(f"Merging asset: {i + 1}/{unlinked_livephoto_df.shape[0]}", end="\r")

        payload = json.dumps({"livePhotoVideoId": asset["video_asset_id"]})

        url = f"{api_config['url']}/api/assets/{asset['photo_asset_id']}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": api_config["api-key"],
        }

        result = requests.request("PUT", url=url, headers=headers, data=payload)

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
        # Ensure column order
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

        # Raise exception with summary
        raise RuntimeError(
            f"Failed to update {len(failed_updates)} files. See {out_failed_file} for details."
        )

    return


def save_asset_record(
    df: pd.DataFrame,
    output_dir: str = "output",
    is_test: bool = False,
    is_dry: bool = False,
):
    """Save identified assets to CSV file in the specified output directory.

    Args:
        df: DataFrame containing assets to save
        output_dir: Directory where files will be saved (created if it doesn't exist)
        is_test: Whether this is a test run
        is_dry: Whether this is a dry run

    Returns:
        str: Path to saved file
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    if is_test:
        filename = f"TEST_RUN_linked_asset_{timestamp}.csv".replace("-", "_")
    elif is_dry:
        filename = f"DRY_RUN_linked_asset_{timestamp}.csv".replace("-", "_")
    else:
        filename = f"linked_assets_{timestamp}.csv".replace("-", "_")

    # Join the output directory with the filename
    out_file = os.path.join(output_dir, filename)

    df.to_csv(out_file, index=False)
    print(f"Record of identified Live Photo/Video assets saved to: {out_file}")
    return out_file


def repair_live_photos(
    immich_api_config: dict,
    immich_db_config: dict,
    user_config: dict,
    dry_run: bool = False,
    test_run: bool = False,
):
    print("1/2: Identifying unlinked Live Photo assets...")
    unlinked_photo_assets_df = get_unlinked_livephoto_ids(
        db_config=immich_db_config, user_config=user_config
    )
    print(unlinked_photo_assets_df)
    print(f"Identified {unlinked_photo_assets_df.shape[0]} unlinked Live Photos.")
    print_example_unlinked_photo(
        asset=unlinked_photo_assets_df.loc[0], api_config=immich_api_config
    )

    if dry_run:
        confirm_dryrun_save = get_confirmation(
            "Would you like to save a record of the assets? [y/n] "
        )

        if confirm_dryrun_save:
            save_asset_record(unlinked_photo_assets_df, is_dry=True)

        print("Dry run of Live Photo linking completed.")
        return

    # Save record

    if test_run:
        print("\n============= TEST RUN ACTIVE ============\n")
        print("Processing only the first asset as a test.")
        print("==========================================\n")
        unlinked_photo_assets_df = unlinked_photo_assets_df.head(1)

    # Confirm Link
    confirm_link = get_confirmation(
        f"Would you like to link the asset{'s' if unlinked_photo_assets_df.shape[0] > 1 else ''}? [y/n] "
    )
    if not confirm_link:
        print("Live Photo linking cancelled.")
        return None

    print("\n2/2: Linking Live Photos and Live Video assets...")
    save_asset_record(unlinked_photo_assets_df, is_test=test_run)
    link_livephoto_assets(
        unlinked_livephoto_df=unlinked_photo_assets_df, api_config=immich_api_config
    )

    print("Live Photos linking complete!")

    return


if __name__ == "__main__":
    # ================================================
    # ⚠️ BEFORE RUNNING: ⚠️
    # 1. Ensure you have a database backup
    # 2. Run the script with `--dry-run` and `--test-run` for testing
    # ================================================
    args = parse_link_args()
    config = load_config(args.config)

    repair_live_photos(
        immich_api_config=config["api"],
        immich_db_config=config["database"],
        user_config=config["user-info"],
        dry_run=args.dry_run,
        test_run=args.test_run,
    )
