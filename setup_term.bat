@echo off
chcp 65001 >nul
title AETHER TERM Setup
setlocal EnableDelayedExpansion

echo.
echo  ##  ##  ####  #####    ####     #####  ##### #####   ##   ##
echo  ##  ## ##  ## ##  ##  ##  ##      ##   ##    ##  ## ####  ####
echo  ##  ## ###### #####   ######      ##   ####  #####   ##   ##
echo   ####  ##  ## ## ##   ##  ##      ##   ##    ## ##
echo    ##   ##  ## ##  ##  ##  ##      ##   ##### ##  ##
echo.
echo                    Aether Term  -  Remote Setup
echo  -------------------------------------------------------------------------------------
echo.
echo  This script installs Aether Term on this computer.
echo  It will check for Git and Python, install them if needed,
echo  clone the repository, install dependencies, and create a
echo  desktop shortcut.
echo.
echo  Press Ctrl+C to cancel, or
pause

:: ═══════════════════════════════════════════════════════════════════
:: Step 1: Check / install Git
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  [1/5] Checking for Git...
where git >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=3 delims= " %%v in ('git --version 2^>^&1') do echo  Git found: %%v
    goto git_ok
)

echo  [!] Git is not installed.
echo.

:: Try winget
where winget >nul 2>&1
if errorlevel 1 goto git_manual

echo  Git can be installed automatically using winget.
echo.
set /p GIT_INSTALL="  Install Git now? [Y/N] > "
if /i "!GIT_INSTALL!" NEQ "Y" goto git_manual

echo.
echo  Installing Git via winget (this may take a minute)...
winget install Git.Git --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto git_manual

echo.
echo  Git installed successfully.
echo  Please CLOSE this window and run setup_term.bat again
echo  so the new PATH takes effect.
echo.
pause
exit /b 0

:git_manual
echo  Please install Git manually from:
echo.
echo    https://git-scm.com/downloads
echo.
echo  Make sure to select "Add to PATH" during installation.
echo  After installing, re-run this script.
echo.
pause
exit /b 1

:git_ok

:: ═══════════════════════════════════════════════════════════════════
:: Step 2: Check / install Python
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  [2/5] Checking for Python...

set "PY="

:: Try py launcher first (most reliable on Windows)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=py -3"
        goto python_found
    )
)

:: Try python
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=python"
        goto python_found
    )
)

:: Try python3
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=python3"
        goto python_found
    )
)

:: Python not found
echo  [!] Python is not installed.
echo.

where winget >nul 2>&1
if errorlevel 1 goto python_manual

echo  Python can be installed automatically using winget.
echo.
set /p PY_INSTALL="  Install Python now? [Y/N] > "
if /i "!PY_INSTALL!" NEQ "Y" goto python_manual

echo.
echo  Installing Python via winget (this may take a minute)...
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto python_manual

echo.
echo  Python installed successfully.
echo  Please CLOSE this window and run setup_term.bat again
echo  so the new PATH takes effect.
echo.
pause
exit /b 0

:python_manual
echo  Please install Python 3.10 or later from:
echo.
echo    https://www.python.org/downloads/
echo.
echo  IMPORTANT: Check "Add Python to PATH" during installation.
echo  After installing, re-run this script.
echo.
pause
exit /b 1

:python_found
for /f "tokens=2 delims= " %%v in ('!PY! --version 2^>^&1') do set "PY_VER=%%v"
echo  Python found: !PY! (version !PY_VER!)

:: Validate version >= 3.10
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if !PY_MAJOR! LSS 3 (
    echo  [ERROR] Python 3.10 or later required. Found !PY_VER!.
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo  [ERROR] Python 3.10 or later required. Found !PY_VER!.
    pause
    exit /b 1
)

:: ═══════════════════════════════════════════════════════════════════
:: Step 3: Clone or update the repository
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  [3/5] Setting up Aether Term...
echo.

set "DEFAULT_DIR=%USERPROFILE%\aether-term"
echo  Where would you like to install AETHER TERM?
echo  Press Enter for default: %DEFAULT_DIR%
echo.
set /p "INSTALL_DIR=  Install folder: "
if "!INSTALL_DIR!"=="" set "INSTALL_DIR=%DEFAULT_DIR%"

:: Expand any environment variables / relative paths
for %%i in ("!INSTALL_DIR!") do set "INSTALL_DIR=%%~fi"

echo.
echo  Installing to: !INSTALL_DIR!
echo.

if exist "!INSTALL_DIR!\.git" (
    echo  Repository already exists. Pulling latest changes...
    pushd "!INSTALL_DIR!"
    git pull --ff-only
    popd
) else (
    if exist "!INSTALL_DIR!\src\main.py" (
        echo  [ERROR] Folder already contains files but is not a git repo.
        echo  Please choose an empty folder or delete the existing files.
        pause
        exit /b 1
    )
    echo  Cloning Aether Term repository...
    git clone https://github.com/KK4ODA/aether-term.git "!INSTALL_DIR!"
    if errorlevel 1 (
        echo.
        echo  [ERROR] git clone failed. Check your internet connection.
        pause
        exit /b 1
    )
)
echo.
echo  Repository ready.

:: ═══════════════════════════════════════════════════════════════════
:: Step 4: Install Python dependencies
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  [4/5] Checking Python dependencies...
echo.

set MISSING=0

!PY! -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] PyQt6
    set MISSING=1
)

!PY! -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] cryptography
    set MISSING=1
)

!PY! -c "import serial" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] pyserial
    set MISSING=1
)

if !MISSING!==1 (
    echo.
    echo  Installing required packages...
    !PY! -m pip install PyQt6 cryptography pyserial certifi
    if errorlevel 1 (
        echo.
        echo  [ERROR] pip install failed. Please run manually:
        echo    !PY! -m pip install PyQt6 cryptography pyserial certifi
        pause
        exit /b 1
    )
    echo.
    echo  Dependencies installed.
) else (
    echo  All dependencies satisfied.
)

:: ═══════════════════════════════════════════════════════════════════
:: Step 5: Create launcher and desktop shortcut
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  [5/5] Creating launcher and shortcut...

:: Create start_term.bat inside the install folder
> "!INSTALL_DIR!\start_term.bat" (
    echo @echo off
    echo chcp 65001 ^>nul
    echo title AETHER TERM
    echo cd /d "%%~dp0"
    echo !PY! src\main.py
    echo pause
)

echo  Created start_term.bat

:: Create desktop shortcut
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\AETHER TERM.lnk"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '!INSTALL_DIR!\start_term.bat'; $sc.WorkingDirectory = '!INSTALL_DIR!'; $sc.Description = 'Aether Term - BBS Terminal Client for VARA and Aether HF'; $sc.Save()"

if exist "%SHORTCUT%" (
    echo  Desktop shortcut created: AETHER TERM
) else (
    echo  [WARNING] Could not create desktop shortcut.
    echo  You can run start_term.bat from: !INSTALL_DIR!
)

:: ═══════════════════════════════════════════════════════════════════
:: Done
:: ═══════════════════════════════════════════════════════════════════
echo.
echo  =====================================================================
echo.
echo   Setup complete!
echo.
echo   To launch AETHER TERM:
echo     - Double-click "AETHER TERM" on your desktop
echo     - Or run: !INSTALL_DIR!\start_term.bat
echo.
echo   Updates are checked automatically on startup.
echo   To update manually: Help ^> Check for Updates
echo.
echo  =====================================================================
echo.
pause
endlocal
