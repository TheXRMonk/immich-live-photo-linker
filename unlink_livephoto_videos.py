"""
Immich Live Photo Unlinker Script

Features:
- Unlinks previously linked Live Photos using the audit CSV
- Interactive confirmation prompts
- Dry run mode
- Audit trail for failed unlinks

Usage:
1. Configure API settings in the `config.yaml` file
2. Run: python unlink_livephoto_videos.py --linked-csv PATH_TO_CSV [flags]

Safety:
- Always test with --dry-run first
"""

import requests
import pandas as pd
from datetime import datetime
from utils import get_api_headers, get_confirmation, load_config, parse_unlink_args


def unlink_livephoto_assets(linked_assets_df: pd.DataFrame, api_config: dict):
    """Remove Live Photo links through Immich API.

    Uses PUT /api/assets/{id} to clear the livePhotoVideoId field.

    Args:
        linked_assets_df: DataFrame containing previously linked assets.
        api_config: Dictionary containing Immich API endpoint and credentials.
    """
    failed_updates = []
    successful_updates = 0
    headers = get_api_headers(api_config, content_type=True)

    for i, asset in linked_assets_df.iterrows():
        print(f"Unlinking asset: {i + 1}/{linked_assets_df.shape[0]}", end="\r")

        url = f"{api_config['url']}/api/assets/{asset['photo_asset_id']}"
        payload = {"livePhotoVideoId": None}

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
                    "error_status": result.status_code,
                    "error_message": error_msg,
                }
            )

    print("\nUnlink Summary:")
    print(f"Successfully unlinked {successful_updates} files.")

    if failed_updates:
        timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
        out_failed_file = f"failed_unlinks_{timestamp}.csv"

        failed_df = pd.DataFrame(failed_updates)
        failed_df.to_csv(out_failed_file, index=False)
        raise RuntimeError(
            f"Failed to unlink {len(failed_updates)} files. See {out_failed_file} for details."
        )


def unlink_from_csv(csv_path: str, api_config: dict, dry_run: bool = False):
    """Main function to unlink Live Photos from audit CSV.

    Args:
        csv_path: Path to the audit CSV from linking script
        api_config: Dictionary containing Immich API endpoint and credentials
        dry_run: If True, only show what would be unlinked
    """
    # Load and validate CSV
    try:
        linked_assets_df = pd.read_csv(csv_path)
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find CSV file: {csv_path}")

    # Check required columns
    required_columns = ["photo_asset_id", "photo_filename"]
    missing_columns = set(required_columns) - set(linked_assets_df.columns)
    if missing_columns:
        raise ValueError(f"CSV missing required columns: {', '.join(missing_columns)}")

    # Check if DataFrame is empty
    if linked_assets_df.empty:
        print("No linked assets found in CSV file.")
        return

    print(f"Found {linked_assets_df.shape[0]} linked Live Photos to unlink.")

    if dry_run:
        print("Dry run complete - no files were unlinked.")
        return

    confirm_unlink = get_confirmation("Would you like to unlink these assets? [y/n] ")
    if not confirm_unlink:
        print("Unlinking cancelled.")
        return

    unlink_livephoto_assets(linked_assets_df, api_config)
    print("Live Photos unlinking complete!")

    return


if __name__ == "__main__":
    # ================================================
    # ⚠️ BEFORE RUNNING: ⚠️
    # Run the script with --dry-run for testing
    # ================================================
    args = parse_unlink_args()
    config = load_config(args.config)

    unlink_from_csv(
        csv_path=args.linked_csv,
        api_config=config["api"],
        dry_run=args.dry_run,
    )
