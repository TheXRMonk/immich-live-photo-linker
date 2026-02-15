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
        "database": ["host", "dbname", "user", "password", "port"],
        "user-info": ["name"]
    }

    for section, keys in required.items():
        if section not in config:
            raise KeyError(f"Missing section: {section}")
        for key in keys:
            if not config[section].get(key):
                raise KeyError(f"Missing required config: {section}.{key}")

    # Connectivity Check
    try:
        url = config['api']['url'].rstrip('/')
        ping = requests.get(f"{url}/api/server/ping", timeout=5)
        ping.raise_for_status()
        
        auth = requests.get(
            f"{url}/api/users/me",
            headers={"x-api-key": config['api']['api-key']},
            timeout=5
        )
        if auth.status_code != 200:
            raise ConnectionError("API Key invalid or insufficient permissions.")
    except Exception as e:
        raise ConnectionError(f"Immich Connectivity Error: {e}")


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
        "--test-run", action="store_true", help="Process only one asset as a test"
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
    config = {"api": {}, "database": {}, "user-info": {}}

    # 1. Try loading from file if it exists
    if Path(config_path).is_file():
        with open(config_path, "r") as f:
            file_data = yaml.safe_load(f)
            if file_data:
                config.update(file_data)

    # 2. Overwrite/Fill with Environment Variables & Defaults
    config["user-info"]["name"] = os.getenv("IMMICH_USERNAME", config["user-info"].get("name"))
    
    config["api"]["api-key"] = os.getenv("IMMICH_API_KEY", config["api"].get("api-key"))
    config["api"]["url"] = os.getenv("IMMICH_URL", config["api"].get("url"))

    config["database"]["host"] = os.getenv("DB_HOST", config["database"].get("host", "immich_postgres"))
    config["database"]["dbname"] = os.getenv("DB_NAME", config["database"].get("dbname", "immich"))
    config["database"]["user"] = os.getenv("DB_USER", config["database"].get("user", "postgres"))
    config["database"]["password"] = os.getenv("DB_PASSWORD", config["database"].get("password"))
    config["database"]["port"] = os.getenv("DB_PORT", config["database"].get("port", "5432"))

    validate_config(config)
    return config
