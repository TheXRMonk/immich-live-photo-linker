# Immich Live Photo Linker

A utility script that uses the Immich API to fix unlinked iOS Live Photos in
Immich by connecting HEIC/JPEG photos with their corresponding MOV/MP4 video
components.

**Key Features:**
- Identifies and links unlinked Live Photo/Video pairs using only the Immich API
- No direct database access required
- Interactive confirmation prompts
- Validates server connection and API credentials
- Creates audit trail CSVs for recovery if needed
- Dry-run and single-test-run modes

## Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Installation & Configuration](#installation--configuration)
- [Detailed Usage](#detailed-usage)
  - [Link Script](#link-script)
  - [Unlink Script](#unlink-script)
- [Notes](#notes)

## Overview

iOS Live Photos consist of a photo (HEIC/JPEG) and video (MOV) component. When
importing Live Photos into Immich, sometimes the link between these components
can be lost. This script identifies and repairs these broken connections.

While you can link Live Photos/Videos one-by-one in the Immich web app, this
script automates the process for handling thousands of images.

## Quick Start

1. Clone repo and install requirements
2. Configure `config.yaml` with your Immich API key and URL
3. Run linking script with safety checks:
   ```bash
   python link_livephoto_videos.py --dry-run     # Test configuration
   python link_livephoto_videos.py --test-run    # Process single asset
   python link_livephoto_videos.py               # Process all assets
   ```

## Requirements

- Python 3.9+
- Immich API key ([how to obtain one](https://immich.app/docs/features/command-line-interface#obtain-the-api-key))
- Script package dependencies (`requirements.txt`)

## Installation & Configuration

1. Clone this repository
2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Update `config.yaml` with your settings:
   - Immich API key
   - Immich server URL

   Alternatively, set environment variables:
   ```bash
   export IMMICH_API_KEY="your-api-key"
   export IMMICH_URL="http://your-immich-url:port"
   ```

## Detailed Usage

### Link Script

Run the script with different modes:

```bash
# Dry run to test configuration (recommended first step)
python link_livephoto_videos.py --dry-run

# Test run to process only one asset (recommended second step)
python link_livephoto_videos.py --test-run

# Full run to process all unlinked assets
python link_livephoto_videos.py

# Using a custom config file
python link_livephoto_videos.py --config my_custom_config.yaml
```

Example output:
```bash
jacob@server:~/immich_scripts$ python link_livephoto_videos.py 
1/2: Identifying unlinked Live Photo assets...
Identified 1753 unlinked Live Photos.
Example Unlinked Live Photo/Video File Information:
    - Live Photo Original Filename: 2DE2659F-F48E-4396-91E3-A4C302231853.heic
    - Live Photo Creation Date: 2022-06-03T21:02:35.193Z
    - Live Video Original Filename: 2DE2659F-F48E-4396-91E3-A4C302231853_3.mov
    - Live Video Creation Date: 2022-06-03T21:02:34.000Z
Would you like to link these assets? [y/n] y

2/2: Linking Live Photos and Live Video assets...
Record of identified Live Photo/Video assets saved to: linked_assets_2025_01_26_044630.csv
Merging asset: 1753/1753
Update Summary:
Successfully linked 1753 files.
Live Photos linking complete!
```

### Unlink Script

If issues occur, use the unlinking script to revert changes:

```bash
# Dry run to test
python unlink_livephoto_videos.py --linked-csv "path/to/linked_assets_audit.csv" --dry-run

# Process the unlinking
python unlink_livephoto_videos.py --linked-csv "path/to/linked_assets_audit.csv"

# Using a custom config file
python unlink_livephoto_videos.py --linked-csv "path/to/linked_assets_audit.csv" --config my_custom_config.yaml
```

## Notes

- Designed and tested for iOS Live Photos
- Uses only the Immich REST API — no direct database access needed
- The linking script creates a CSV audit file that can be used with the
  unlinking script if needed
- Use `--config` flag to specify a different config file location if needed
