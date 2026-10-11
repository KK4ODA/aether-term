"""
_frozen.py — Path resolution helper for PyInstaller-frozen builds.

When Aether Term is run from source, paths are resolved relative to the source tree.
When frozen with PyInstaller (--onefile or --onedir), bundled data files live
under sys._MEIPASS and the executable is at sys.executable.

Usage:
    from _frozen import APP_DIR, RESOURCE_DIR, is_frozen

    icon_path = RESOURCE_DIR / "arrow_down.svg"
"""

import sys
import os
from pathlib import Path

# True when running as a PyInstaller bundle
is_frozen: bool = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

if is_frozen:
    # PyInstaller extracts bundled data to a temp folder (_MEIPASS)
    # The executable itself is at sys.executable
    BUNDLE_DIR: Path = Path(sys._MEIPASS)
    EXE_DIR: Path = Path(sys.executable).parent
else:
    # Running from source — use the directory containing main.py
    BUNDLE_DIR = Path(__file__).parent
    EXE_DIR = Path(__file__).parent

# Application root (source tree root or bundle root)
APP_DIR: Path = BUNDLE_DIR

# Resource directory (bundled data)
RESOURCE_DIR: Path = APP_DIR / "resources"
