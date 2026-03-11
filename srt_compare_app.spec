# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for SRT Compare Desktop Application
Produces a SINGLE executable file (--onefile mode).
Works on both Windows and Linux.
"""

import os
import sys
import platform

block_cipher = None

IS_WINDOWS = platform.system() == 'Windows'
EXE_NAME = 'SRT-Compare'
base_path = os.path.abspath('.')

# Icon (optional — place icon.ico in static/ if you want a custom icon)
icon_path = os.path.join(base_path, 'static', 'icon.ico')
icon_file = icon_path if os.path.exists(icon_path) else None

a = Analysis(
    ['run_desktop.py'],
    pathex=[base_path],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('main.py', '.'),
        ('database.py', '.'),
        ('models.py', '.'),
        ('srt_compare.py', '.'),
        ('translator.py', '.'),
        ('auth.py', '.'),
    ],
    hiddenimports=[
        # FastAPI
        'fastapi', 'fastapi.middleware', 'fastapi.middleware.cors',
        'fastapi.responses', 'fastapi.staticfiles',
        # Starlette
        'starlette', 'starlette.responses', 'starlette.staticfiles',
        'starlette.middleware', 'starlette.middleware.cors',
        'starlette.routing', 'starlette.applications',
        # Uvicorn
        'uvicorn', 'uvicorn.config', 'uvicorn.main',
        'uvicorn.protocols', 'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.lifespan.off',
        'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
        # HTTP
        'httptools', 'httptools.parser', 'httptools.parser.parser', 'h11',
        'websockets',
        # SQLite
        'aiosqlite', 'sqlite3',
        # Pydantic
        'pydantic', 'pydantic.fields', 'pydantic_core', 'annotated_types',
        # Auth
        'jose', 'jose.jwt',
        'passlib', 'passlib.context', 'passlib.handlers', 'passlib.handlers.bcrypt',
        'bcrypt',
        # OpenAI
        'openai',
        # Multipart
        'multipart', 'python_multipart',
        # Other
        'dotenv', 'email_validator',
        'anyio', 'anyio._backends', 'anyio._backends._asyncio',
        'sniffio', 'idna', 'certifi', 'httpcore', 'httpx',
        'typing_extensions',
        # App modules
        'main', 'database', 'models', 'srt_compare', 'translator', 'auth',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'cv2', 'torch', 'tensorflow', 'streamlit',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# === SINGLE-FILE EXE (--onefile) ===
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=not IS_WINDOWS,
    upx=True,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    icon=icon_file,
)
