@echo off
title Large Image Viewer
echo.
echo ========================================
echo   Large Image Viewer
echo ========================================
echo.

:: Check if Docker is available and prefer it (has libvips built-in)
docker --version >nul 2>&1
if not errorlevel 1 (
    echo Using Docker (recommended)...
    docker-compose up --build
    goto :end
)

:: Fallback to native Python
echo Docker not found, trying native Python...
echo.

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Neither Docker nor Python is installed.
    echo.
    echo Option 1: Install Docker Desktop from https://docker.com
    echo Option 2: Install Python from https://python.org
    echo           Then install libvips: https://www.libvips.org/install.html
    pause
    exit /b 1
)

:: Check if pyvips can load libvips
python -c "import pyvips; pyvips.Image.black(1,1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: libvips library not found.
    echo.
    echo Please install libvips:
    echo   1. Download from: https://github.com/libvips/libvips/releases
    echo   2. Extract and add the 'bin' folder to your PATH
    echo.
    echo Or use Docker instead (recommended):
    echo   docker-compose up --build
    pause
    exit /b 1
)

:: Run the viewer
python "%~dp0run.py"

:end
pause
