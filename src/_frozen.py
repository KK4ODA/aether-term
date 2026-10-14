"""
_frozen.py — Where Aether Term's own files are.

EXE_DIR is the folder holding "Aether Term.exe" in a PyInstaller build
(a portable install keeps its Hamlib download beside it), or src/ when
run from source.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    EXE_DIR: Path = Path(sys.executable).parent
else:
    EXE_DIR = Path(__file__).parent
