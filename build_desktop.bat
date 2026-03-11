@echo off
REM ============================================
REM SRT Compare - Build Single EXE (Windows)
REM Produces ONE file: dist\SRT-Compare.exe
REM No Python needed on the target machine.
REM ============================================

setlocal enabledelayedexpansion

echo ============================================
echo   Building SRT Compare (single .exe)
echo ============================================
echo.

REM Check Python
echo [1/5] Checking Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

REM Install build deps
echo [2/5] Installing build dependencies...
python -m pip install --upgrade pip
python -m pip install pyinstaller
echo.

REM Install app deps
echo [3/5] Installing application dependencies...
python -m pip install -r requirements.txt
echo.

REM Check frontend
echo [4/5] Checking frontend...
if not exist "static\index.html" (
    echo ERROR: static\index.html not found!
    pause
    exit /b 1
)
echo   OK
echo.

REM Build
echo [5/5] Building single EXE...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
python -m PyInstaller srt_compare_app.spec --clean --noconfirm
echo.

REM Verify
if exist "dist\SRT-Compare.exe" (
    echo ============================================
    echo   BUILD SUCCESSFUL
    echo ============================================
    echo.
    echo   Output: dist\SRT-Compare.exe
    echo.
    echo   Just give this single file to users.
    echo   Double-click to run. No install needed.
    echo   Uses SQLite - no database setup required.
    echo ============================================
) else (
    echo BUILD FAILED - exe not found in dist\
)

echo.
pause
