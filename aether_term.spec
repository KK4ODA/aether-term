# -*- mode: python ; coding: utf-8 -*-
"""
aether_term.spec — PyInstaller spec file for Aether Term.

Build with:
    pyinstaller aether_term.spec

Produces: dist/Aether Term/Aether Term.exe  (one-directory mode)
    — or —
    pyinstaller aether_term.spec --onefile    (single .exe, slower startup)

One-directory mode is recommended because:
  - Faster startup (no temp extraction)
  - Easier to bundle Hamlib alongside
  - Easier to debug / inspect
"""

import sys
import os
from pathlib import Path

block_cipher = None

# ── Paths ────────────────────────────────────────────────────────
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
SRC_DIR = os.path.join(SPEC_DIR, 'src')

# ── Data files to bundle ─────────────────────────────────────────
# (source_path, destination_folder_in_bundle)
datas = [
    (os.path.join(SPEC_DIR, 'version.txt'), '.'),
]

# ── Hidden imports ───────────────────────────────────────────────
# PyInstaller sometimes misses these dynamic imports
hiddenimports = [
    # Core app modules
    'config',
    'passwords',
    'auth',
    '_frozen',
    'gui',
    'gui.main_window',
    'gui.settings_dialog',
    'gui.hamlib_settings',
    'gui.terminal_widget',
    'gui.sn_graph',
    'gui.password_dialog',
    'gui.profile_dialog',
    'gui.theme',
    'gui.update_dialog',
    'updater',
    'vara',
    'vara.modem',
    'vara.connection',
    'vara.ptt',
    'vara.rig_client',
    'vara.omnirig',
    'vara.hamlib',
    'vara.hamlib_download',
    'vara.flrig',
    'vara.local_test',
    'vara.agwpe',
    'vara.agwpe_modem',
    'vara.kiss_modem',
    'ax25',
    'ax25.frame',
    'ax25.kiss',
    'ax25.link',
    'tnc',
    'tnc.transports',
    'tnc.ble',
    'gui.kiss_settings',
    'serial',
    'serial.tools.list_ports',
    'aether',
    'aether.control',

    # PyQt6 plugins
    'PyQt6.sip',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',

    # Crypto (Fernet, for the saved-password file)
    'cryptography',
    'cryptography.fernet',

    # Keyring backends (optional — OS credential storage)
    'keyring',
    'keyring.backends',

    # Standard library modules that may be dynamically loaded
    'json',
    'hashlib',
    'hmac',
    'ssl',
    'certifi',
    'urllib.request',
    'urllib.error',
    'zipfile',
    'tarfile',
    'shutil',
    'xmlrpc',
    'xmlrpc.client',
]

# ── Bluetooth LE (bleak) loads its OS backend dynamically ────────
try:
    from PyInstaller.utils.hooks import collect_submodules
    hiddenimports += collect_submodules('bleak')
    if sys.platform == 'win32':
        hiddenimports += collect_submodules('winrt')
except Exception as e:  # bleak not installed: BLE is unavailable in this build
    print(f"WARNING: bleak not bundled ({e})")

# ── Optional: pywin32 for OmniRig (Windows only) ────────────────
if sys.platform == 'win32':
    hiddenimports += [
        'win32com',
        'win32com.client',
        'pythoncom',
        'pywintypes',
    ]

# ── Exclude unnecessary large packages ───────────────────────────
excludes = [
    'tkinter',
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'PIL',
    'cv2',
    'test',
    'unittest',
]

# ── Analysis ─────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(SRC_DIR, 'main.py')],
    pathex=[SRC_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Filter out unnecessary Qt plugins to reduce size ─────────────
QT_PLUGIN_KEEP = {
    'platforms',
    'styles',
    'imageformats',
    'iconengines',
}

filtered_binaries = []
for dest, src, typecode in a.binaries:
    if 'PyQt6' not in dest and 'Qt6' not in dest:
        filtered_binaries.append((dest, src, typecode))
        continue
    if 'plugins' in dest.replace('\\', '/'):
        plugin_dir = dest.replace('\\', '/').split('plugins/')[-1].split('/')[0]
        if plugin_dir in QT_PLUGIN_KEEP:
            filtered_binaries.append((dest, src, typecode))
    else:
        filtered_binaries.append((dest, src, typecode))

a.binaries = filtered_binaries

# ── PYZ (Python bytecode archive) ────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE ──────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Aether Term',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── COLLECT (one-directory bundle) ───────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Aether Term',
)
