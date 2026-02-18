"""Utility functions for the Immich Live Photo Linker/Unlinker scripts."""

import os
import requests
import argparse
import yaml
from pathlib import Path


def get_confirmation(prompt: str) -> bool:
    """Get validated yes/no input from user."""
    while True:
        response = input(prompt).lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False
        print("Invalid input. Please enter y/yes or n/no")


def validate_config(config: dict):
    """Validate configuration with server connectivity check."""
    required = {
        "api": ["api-key", "url"],
    }

    for section, keys in required.items():
        if section not in config:
            raise KeyError(f"Missing section: {section}")
        for key in keys:
            if not config[section].get(key):
                raise KeyError(f"Missing required config: {section}.{key}")

    # Connectivity Check
    try:
        url = config["api"]["url"].rstrip("/")
        ping = requests.get(f"{url}/api/server/ping", timeout=5)
        ping.raise_for_status()

        auth = requests.get(
            f"{url}/api/users/me",
            headers={"x-api-key": config["api"]["api-key"]},
            timeout=5,
        )
        if auth.status_code != 200:
            raise ConnectionError("API Key invalid or insufficient permissions.")
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"Immich Connectivity Error: {e}")


def get_api_headers(api_config: dict, content_type: bool = False) -> dict:
    """Build standard API headers for Immich requests.

    Args:
        api_config: Dictionary containing API endpoint and credentials.
        content_type: Whether to include Content-Type header for JSON payloads.

    Returns:
        Dictionary of HTTP headers.
    """
    headers = {
        "Accept": "application/json",
        "x-api-key": api_config["api-key"],
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def search_assets(api_config: dict, search_params: dict) -> list[dict]:
    """Fetch all assets matching search criteria using paginated metadata search.

    Uses POST /api/search/metadata with automatic pagination.

    Args:
        api_config: Dictionary containing Immich API endpoint and credentials.
        search_params: Dictionary of MetadataSearchDto parameters.

    Returns:
        List of AssetResponseDto dictionaries.
    """
    url = f"{api_config['url']}/api/search/metadata"
    headers = get_api_headers(api_config, content_type=True)

    all_assets = []
    page = 1
    page_size = 1000

    while True:
        params = {**search_params, "page": page, "size": page_size}
        response = requests.post(url, headers=headers, json=params)
        response.raise_for_status()

        data = response.json()
        assets_data = data.get("assets", {})
        items = assets_data.get("items", [])
        all_assets.extend(items)

        next_page = assets_data.get("nextPage")
        if not next_page or len(items) < page_size:
            break

        page += 1

    return all_assets


def parse_link_args() -> argparse.Namespace:
    """Parse command line arguments for Immich Live Photo Linker.

    Returns:
        argparse.Namespace: Parsed command line arguments containing:
            - dry_run (bool): Whether to perform a dry run
            - test_run (bool): Whether to process only one asset
            - config (str): Path to configuration file
    """
    parser = argparse.ArgumentParser(
        description="Link Live Photo/Video pairs in Immich media server"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making changes",
    )
    parser.add_argument(
        "--test-run",
        action="store_true",
        help="Process only one asset as a test",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )

    return parser.parse_args()


def parse_unlink_args() -> argparse.Namespace:
    """Parse command line arguments for Immich Live Photo Unlinker.

    Returns:
        argparse.Namespace: Parsed command line arguments containing:
            - dry_run (bool): Whether to perform a dry run
            - config (str): Path to configuration file
            - linked_csv (str): Path to CSV file containing linked assets
    """
    parser = argparse.ArgumentParser(
        description="Unlink previously linked Live Photo/Video pairs in Immich media server"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making changes",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--linked-csv",
        required=True,
        help="Path to CSV file containing linked assets to unlink",
    )

    return parser.parse_args()


def load_config(config_path: str) -> dict:
    """Loads config prioritizing Env Vars, then YAML file, then Defaults."""
    config = {"api": {}}

    # 1. Try loading from file if it exists
    if Path(config_path).is_file():
        with open(config_path, "r") as f:
            file_data = yaml.safe_load(f)
            if file_data:
                config.update(file_data)

    # 2. Overwrite/Fill with Environment Variables
    config["api"]["api-key"] = os.getenv(
        "IMMICH_API_KEY", config["api"].get("api-key")
    )
    config["api"]["url"] = os.getenv("IMMICH_URL", config["api"].get("url"))

    validate_config(config)
    return config
