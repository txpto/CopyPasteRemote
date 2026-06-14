#!/usr/bin/env python3
"""Entry point for the CopyPasteRemote Windows client.

Examples
--------
    python run_client.py --setup
    python run_client.py --check
    python run_client.py             # run the tray app
    python run_client.py --no-tray   # headless (hotkeys only)
"""

import sys

from cpr_client.main import main

if __name__ == "__main__":
    sys.exit(main())
