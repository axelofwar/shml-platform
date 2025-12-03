#!/usr/bin/env python3
"""
Platform Admin - Main entry point.

This script can be run directly:
    ./platform_admin.py
    ./platform_admin.py user list
    ./platform_admin.py --help

Or as a module:
    python -m platform_admin
    python -m platform_admin user list
"""

import sys
import os

# Add the scripts directory to path so we can import platform_admin
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from platform_admin.cli import main

if __name__ == "__main__":
    main()
