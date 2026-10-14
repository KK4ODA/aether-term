# Building the Aether Term Windows Installer

## The 3-Step Version

1. **Install Python 3.10+** from https://www.python.org/downloads/
   - **Check "Add Python to PATH"** during installation — this is critical

2. **Install Inno Setup 6** from https://jrsoftware.org/isdl.php
   - Use the default install location — the build script auto-detects it
   - This creates the `Aether_Term_Setup_<version>.exe` installer
   - Skip this if you only want a portable .zip

3. **Double-click `build.bat`**
   - It installs all pip dependencies for you
   - It runs PyInstaller (`aether_term.spec`) to create the .exe
   - It runs Inno Setup to create the installer
   - It creates a portable .zip as a fallback

When it finishes you'll find these in the `dist\` folder:

| File | What it is |
|------|------------|
| `dist\Aether_Term_Setup_<version>.exe` | Installer (Start Menu, uninstaller, the works). Upgrades an existing VARA Term install in place |
| `dist\Aether_Term_Setup_<version>.zip` | The installer, zipped |
| `dist\Aether_Term_Portable_<version>.zip` | Portable zip (extract anywhere, run `Aether Term.exe`) |
| `dist\Aether Term\Aether Term.exe` | Raw build output (used by the above two) |

---

## Cloud builds

PyInstaller doesn't cross-compile, so a Windows .exe must be built on Windows. The GitHub
Actions workflow (`.github/workflows/build_release.yml`) does this on a Windows runner: it
installs Inno Setup, builds the program, the installer, the zipped installer and the portable
zip, and attaches all three to the release (see `docs/RELEASE_CHECKLIST.md`). Run without a
tag, it is a dry run that keeps the files as workflow artifacts.

---

## Aether HF is not bundled

Aether HF is a separate program with its own installer
(https://github.com/KK4ODA/aether-hf/releases). Aether Term only talks to it over TCP, so
nothing from Aether HF goes into this build.

---

## Troubleshooting

**"Python is not installed or not on PATH"**
→ Reinstall Python and check "Add Python to PATH". Or open a new terminal.

**PyInstaller build fails with antivirus warnings**
→ Temporarily disable real-time AV scanning, or add the project folder to exclusions. PyInstaller executables are commonly flagged as false positives.

**Inno Setup not found (but installed)**
→ The script checks standard install paths. If you installed elsewhere, add its folder to your system PATH so `iscc.exe` is reachable.

**Missing module at runtime**
→ Add the module name to `hiddenimports` in `aether_term.spec` and rebuild.

**App icon**
→ There is no icon yet. To add one: put a 256×256 multi-size `aether_term.ico` in the repository root, add `icon='aether_term.ico'` to the `EXE(...)` call in `aether_term.spec`, set `SetupIconFile=aether_term.ico` (and `UninstallDisplayIcon`) in `installer.iss`, and rebuild.
