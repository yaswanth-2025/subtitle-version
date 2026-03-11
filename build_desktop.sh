#!/bin/bash
# ============================================
# SRT Compare - Build Single Executable (Linux)
# Produces ONE file: dist/SRT-Compare
# ============================================

set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "============================================"
echo "  Building SRT Compare (single executable)"
echo "============================================"
echo ""

# Check Python
PYTHON=""
if command -v python3 &>/dev/null; then PYTHON="python3"
elif command -v python &>/dev/null; then PYTHON="python"
else echo "ERROR: Python not found!"; exit 1; fi
echo "[1/5] Python: $($PYTHON --version)"

echo "[2/5] Installing build deps..."
$PYTHON -m pip install --upgrade pip pyinstaller

echo "[3/5] Installing app deps..."
$PYTHON -m pip install -r requirements.txt

echo "[4/5] Checking frontend..."
[ -f "static/index.html" ] || { echo "ERROR: static/index.html missing"; exit 1; }
echo "  OK"

echo "[5/5] Building..."
rm -rf build/ dist/
$PYTHON -m PyInstaller srt_compare_app.spec --clean --noconfirm

if [ -f "dist/SRT-Compare" ]; then
    SIZE=$(du -sh dist/SRT-Compare | cut -f1)
    echo ""
    echo "============================================"
    echo "  BUILD SUCCESSFUL"
    echo "============================================"
    echo "  Output: dist/SRT-Compare ($SIZE)"
    echo "  Just run: ./dist/SRT-Compare"
    echo "  No database setup needed (uses SQLite)"
    echo "============================================"
else
    echo "BUILD FAILED"
    exit 1
fi
