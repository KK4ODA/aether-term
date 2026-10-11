@echo off
REM ═══════════════════════════════════════════════════════════════
REM  build.bat — One-click build for Aether Term Windows installer
REM ═══════════════════════════════════════════════════════════════
REM
REM  This script will:
REM    1. Find Python 3.10–3.13 via the py launcher
REM    2. Install all pip dependencies automatically
REM    3. Build Aether Term exe via PyInstaller
REM    4. Create Aether_Term_Setup_x.y.z.exe via Inno Setup (if installed)
REM    5. Create a portable .zip (run without installing)
REM    6. Zip the installer (avoids antivirus flags on bare .exe)
REM
REM  Usage: Double-click build.bat
REM
REM ═══════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "APP_NAME=Aether Term"
set /p APP_VERSION=<version.txt

echo.
echo  ========================================================
echo    Aether Term v%APP_VERSION% — Windows Build
echo  ========================================================
echo.

REM ══════════════════════════════════════════════════════════════
REM  STEP 1 — Find a compatible Python (3.10–3.13)
REM ══════════════════════════════════════════════════════════════
echo [1/5] Locating Python 3.10-3.13...
echo.

set "PY="

REM Try py launcher with specific versions (preferred: newest stable first)
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 (
            set "PY=py -%%V"
            echo        Found Python %%V via py launcher
        )
    )
)

REM Fallback: try plain "python" and check its version
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=2 delims= " %%A in ('python --version 2^>^&1') do (
            echo %%A | findstr /b "3.10 3.11 3.12 3.13" >nul
            if not errorlevel 1 (
                set "PY=python"
                echo        Found compatible python on PATH
            )
        )
    )
)

if not defined PY (
    echo.
    echo  ERROR: No compatible Python found (need 3.10, 3.11, 3.12, or 3.13^)
    echo.
    echo  Python 3.14 is NOT yet supported by PyInstaller.
    echo.
    echo  Fix:
    echo    1. Download Python 3.12 from:
    echo       https://www.python.org/downloads/release/python-31210/
    echo    2. Run the installer
    echo    3. Run build.bat again
    echo.
    pause
    exit /b 1
)

REM Show the version we'll use
for /f "tokens=*" %%i in ('!PY! --version 2^>^&1') do echo        Using: %%i
echo.

REM ══════════════════════════════════════════════════════════════
REM  STEP 2 — Install dependencies
REM ══════════════════════════════════════════════════════════════
echo [2/5] Installing dependencies (this may take a minute)...

!PY! -m pip install --upgrade pip >nul 2>&1

!PY! -m pip install pyinstaller PyQt6 cryptography pyserial keyring pywin32 certifi --quiet 2>nul

echo        Dependencies OK

REM ══════════════════════════════════════════════════════════════
REM  STEP 3 — Clean previous build
REM ══════════════════════════════════════════════════════════════
echo.
echo [3/5] Cleaning previous build artifacts...
if exist build  rmdir /s /q build  >nul 2>&1
if exist dist   rmdir /s /q dist   >nul 2>&1
echo        Clean

REM ══════════════════════════════════════════════════════════════
REM  STEP 4 — Build with PyInstaller
REM ══════════════════════════════════════════════════════════════
echo.
echo [4/5] Building %APP_NAME%.exe with PyInstaller...
echo        (this takes 1-3 minutes depending on your machine)
echo.

!PY! -m PyInstaller --noconfirm --clean aether_term.spec

if errorlevel 1 (
    echo.
    echo  ========================================================
    echo    BUILD FAILED — see errors above
    echo  ========================================================
    echo.
    echo  Common fixes:
    echo    - Make sure no antivirus is blocking PyInstaller
    echo    - Try running build.bat again
    echo.
    pause
    exit /b 1
)

REM Verify the exe was created
if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo.
    echo  ERROR: dist\%APP_NAME%\%APP_NAME%.exe not found after build.
    pause
    exit /b 1
)

echo.
echo        dist\%APP_NAME%\%APP_NAME%.exe — OK

REM ══════════════════════════════════════════════════════════════
REM  STEP 5 — Create installer or portable zip
REM ══════════════════════════════════════════════════════════════
echo.
echo [5/5] Packaging for distribution...

REM Try Inno Setup first
set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC (
    if exist "%ProgramFiles(x86)%\Inno Setup 6\iscc.exe" (
        set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\iscc.exe"
    )
)
if not defined ISCC (
    if exist "%ProgramFiles%\Inno Setup 6\iscc.exe" (
        set "ISCC=%ProgramFiles%\Inno Setup 6\iscc.exe"
    )
)

if defined ISCC (
    echo        Inno Setup found — building installer...
    echo.
    "!ISCC!" installer.iss
    if not errorlevel 1 (
        echo.
        echo        Installer created!
    ) else (
        echo.
        echo        Inno Setup failed — you can install it from:
        echo        https://jrsoftware.org/isdl.php
    )
)

REM Always create a portable .zip
echo.
echo        Creating portable .zip...
!PY! -c "import shutil; shutil.make_archive('dist/Aether_Term_Portable_%APP_VERSION%', 'zip', 'dist', 'Aether Term')"

REM Zip the installer (bare .exe files get flagged by antivirus / email / browsers)
if exist "dist\Aether_Term_Setup_%APP_VERSION%.exe" (
    echo        Creating installer .zip...
    !PY! -c "import zipfile, os; z=zipfile.ZipFile('dist/Aether_Term_Setup_%APP_VERSION%.zip','w',zipfile.ZIP_DEFLATED); z.write('dist/Aether_Term_Setup_%APP_VERSION%.exe','Aether_Term_Setup_%APP_VERSION%.exe'); z.close()"
)

REM ══════════════════════════════════════════════════════════════
REM  DONE
REM ══════════════════════════════════════════════════════════════
echo.
echo  ========================================================
echo    BUILD SUCCESSFUL
echo  ========================================================
echo.

if exist "dist\Aether_Term_Setup_%APP_VERSION%.exe" (
    echo    Installer:       dist\Aether_Term_Setup_%APP_VERSION%.exe
)
if exist "dist\Aether_Term_Setup_%APP_VERSION%.zip" (
    echo    Installer ZIP:   dist\Aether_Term_Setup_%APP_VERSION%.zip   ^(share this^)
)
if exist "dist\Aether_Term_Portable_%APP_VERSION%.zip" (
    echo    Portable ZIP:    dist\Aether_Term_Portable_%APP_VERSION%.zip
)
echo    Standalone:      dist\Aether Term\Aether Term.exe
echo.
echo  Test it:  dist\Aether Term\Aether Term.exe
echo.
pause
exit /b 0
