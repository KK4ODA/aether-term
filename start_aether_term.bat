@echo off
chcp 65001 >nul
title Aether Term - BBS Terminal Client for VARA and Aether HF

:: -- Aether Term Launcher --------------------------------------------------------------
:: This script sets up the Python environment and launches Aether Term.
:: Place this file in the same folder as main.py.
:: --------------------------------------------------------------------------------

setlocal EnableDelayedExpansion

:: Change to the directory where this bat file lives
cd /d "%~dp0"

echo.
echo     _          _   _                 _____
echo    / \   ___^| ^|_^| ^|__   ___ _ __  ^|_   _^|__ _ __ _ __ ___
echo   / _ \ / _ \ __^| '_ \ / _ \ '__^|   ^| ^|/ _ \ '__^| '_ ` _ \
echo  / ___ \  __/ ^|_^| ^| ^| ^|  __/ ^|      ^| ^|  __/ ^|  ^| ^| ^| ^| ^| ^|
echo /_/   \_\___^|\__^|_^| ^|_^|\___^|_^|      ^|_^|\___^|_^|  ^|_^| ^|_^| ^|_^|
echo.
echo          Aether Term - BBS Terminal Client for VARA and Aether HF
echo  --------------------------------------------------------------------------
echo.

:: -- Find a working Python interpreter -------------------------------------------
::
:: Try three common names in order of preference:
::   1. py     = the Windows Python Launcher (most reliable on Windows)
::   2. python = standard name (on PATH only if user checked the box at install)
::   3. python3
::
:: Whichever works is stored in %PY% and used everywhere below.

set "PY="

:: --- Try "py" first (Windows Python Launcher) ---
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=py -3"
        goto foundpython
    )
)

:: --- Try "python" ---
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=python"
        goto foundpython
    )
)

:: --- Try "python3" ---
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=python3"
        goto foundpython
    )
)

:: -- Python not found ------------------------------------------------------------
echo  [ERROR] Python is not installed or not on PATH.
echo.

:: Try winget auto-install (Windows 10 1709+ / Windows 11)
where winget >nul 2>&1
if errorlevel 1 goto manualinstall

echo  Python can be installed automatically using winget.
echo.
set /p PY_INSTALL="  Install Python now? [Y/N] > "
if /i "!PY_INSTALL!" NEQ "Y" goto manualinstall

echo.
echo  Installing Python via winget...
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto manualinstall

echo.
echo  Python installed successfully.
echo  Please CLOSE this window and run start_aether_term.bat again
echo  so the new PATH takes effect.
echo.
pause
exit /b 0

:manualinstall
echo  Please install Python 3.10 or later from:
echo.
echo    https://www.python.org/downloads/
echo.
echo  IMPORTANT: Check "Add Python to PATH" during installation.
echo  After installing, re-run this script.
echo.
pause
exit /b 1

:: -- Python found -- validate version --------------------------------------------
:foundpython

:: Get version string
for /f "tokens=2 delims= " %%v in ('!PY! --version 2^>^&1') do set "PY_VER=%%v"
echo  Python: !PY! ^(version !PY_VER!^)

:: Parse major.minor
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if !PY_MAJOR! LSS 3 (
    echo  [ERROR] Python 3.10 or later is required. Found !PY_VER!.
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo  [ERROR] Python 3.10 or later is required. Found !PY_VER!.
    pause
    exit /b 1
)

:: -- Check / install dependencies ------------------------------------------------
echo  Checking dependencies...
echo.

set MISSING=0
set "MISSING_LIST="

!PY! -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] PyQt6
    set MISSING=1
    set "MISSING_LIST=!MISSING_LIST! PyQt6"
)

!PY! -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] cryptography
    set MISSING=1
    set "MISSING_LIST=!MISSING_LIST! cryptography"
)

!PY! -c "import certifi" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] certifi
    set MISSING=1
    set "MISSING_LIST=!MISSING_LIST! certifi"
)

!PY! -c "import serial" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] pyserial
    set MISSING=1
    set "MISSING_LIST=!MISSING_LIST! pyserial"
)

!PY! -c "import bleak" >nul 2>&1
if errorlevel 1 (
    echo  [MISSING] bleak
    set MISSING=1
    set "MISSING_LIST=!MISSING_LIST! bleak"
)

:: -- Optional: keyring -----------------------------------------------------------
!PY! -c "import keyring" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  keyring is not installed. It provides OS-level credential storage
    echo  ^(Windows Credential Manager^) for saved BBS passwords.
    echo  Without it, passwords are encrypted with Fernet in a local file.
    echo.
    set /p KEYRING_CHOICE="  Install keyring? [Y/N] > "
    if /i "!KEYRING_CHOICE!"=="Y" (
        echo.
        echo  Installing keyring...
        !PY! -m pip install keyring
        if errorlevel 1 (
            echo  [WARNING] Failed to install keyring.
        ) else (
            echo  keyring installed successfully.
        )
    ) else (
        echo  Skipping keyring.
    )
    echo.
)

:: -- Optional: pywin32 for OmniRig HF PTT control --------------------------------
!PY! -c "import win32com.client" >nul 2>&1
if errorlevel 1 (
    echo  pywin32 is not installed. It is required for OmniRig HF PTT control.
    echo  If you only use VARA FM, you can skip this.
    echo.
    set /p PYWIN32_CHOICE="  Install pywin32? [Y/N] > "
    if /i "!PYWIN32_CHOICE!"=="Y" (
        echo.
        echo  Installing pywin32...
        !PY! -m pip install pywin32
        if errorlevel 1 (
            echo  [WARNING] Failed to install pywin32.
        ) else (
            echo  pywin32 installed successfully.
        )
    ) else (
        echo  Skipping pywin32.
    )
    echo.
)

:: -- Install missing required packages -------------------------------------------
if !MISSING!==1 (
    echo.
    echo  One or more required packages are missing:!MISSING_LIST!
    echo.
    set /p INSTALL_CHOICE="  Install them now? [Y/N] > "
    if /i "!INSTALL_CHOICE!"=="Y" (
        echo.
        echo  Installing dependencies...
        !PY! -m pip install PyQt6 cryptography certifi pyserial bleak
        if errorlevel 1 (
            echo.
            echo  [ERROR] pip install failed. Please run manually:
            echo    !PY! -m pip install PyQt6 cryptography certifi pyserial bleak
            pause
            exit /b 1
        )
        echo.
        echo  Dependencies installed successfully.
    ) else (
        echo.
        echo  Cannot start without required packages. Exiting.
        pause
        exit /b 1
    )
) else (
    echo  All dependencies satisfied.
)

echo.
echo  --------------------------------------------------------------------------
echo  Starting Aether Term...
echo  --------------------------------------------------------------------------
echo.

:: -- Launch the application ------------------------------------------------------
!PY! src\main.py

:: Catch non-zero exit
if errorlevel 1 (
    echo.
    echo  --------------------------------------------------------------------------
    echo  [ERROR] Aether Term exited with an error ^(code %errorlevel%^).
    echo  Check the logs folder for details:
    echo    %USERPROFILE%\Aether Term\logs\aether-term.log
    echo  --------------------------------------------------------------------------
    echo.
    pause
)

endlocal
