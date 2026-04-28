"""
SRT Comparison API - FastAPI Application

Production-ready API for comparing SRT subtitle files with:
- SQLite persistence (zero-config, bundled with Python)
- Comparison history
- Translation with caching
- Export functionality
"""
from fastapi import FastAPI, UploadFile, Form, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List
import json as json_mod
import tempfile
import os
import sys
import io
import hashlib
import pathlib

from database import (
    connect_to_database, close_database_connection, is_database_available,
    insert_comparison, get_comparisons_list, get_comparison_by_id,
    update_comparison_results_db, update_comparison_status_db, delete_comparison_db,
    find_cached_translation, insert_translation, list_translations_db,
    get_translation_by_id, delete_translation_db, clear_all_translations,
)
from models import (
    ComparisonResult, ComparisonSummary, ComparisonResponse,
    ComparisonDetailResponse
)
from srt_compare import compare_srts, results_to_json, results_to_csv, translate_srt_content, generate_bilingual_srt
from translator import get_translator


# --- helpers ---

def _require_db():
    """Raise a JSON-friendly 503 if the database is not available."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available."
        )


def _db_error(action, exc):
    """Convert any database exception into a JSON-friendly 503."""
    print(f"DB error during {action}: {exc}")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Database operation failed: {action}."
    )


def _valid_id(val):
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


def _parse_results(row):
    r = row.get("results", "{}")
    if isinstance(r, str):
        return json_mod.loads(r)
    return r


# --- lifespan ---

@asynccontextmanager
async def lifespan(app):
    home_dir = pathlib.Path.home()
    settings_dir = home_dir / ".srt_compare"
    settings_dir.mkdir(exist_ok=True)
    settings_file = str(settings_dir / "app_settings.json")

    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r') as f:
                settings = json_mod.load(f)
                if settings.get("openai_api_key"):
                    os.environ["OPENAI_API_KEY"] = settings["openai_api_key"]
                if settings.get("gemini_api_key"):
                    os.environ["GEMINI_API_KEY"] = settings["gemini_api_key"]
                if settings.get("claude_api_key"):
                    os.environ["CLAUDE_API_KEY"] = settings["claude_api_key"]
                if settings.get("translation_provider"):
                    os.environ["TRANSLATION_PROVIDER"] = settings["translation_provider"]
                if settings.get("translation_model"):
                    os.environ["TRANSLATION_MODEL"] = settings["translation_model"]
                print(f"✅ Loaded settings from {settings_file}")
                print(f"   Provider: {settings.get('translation_provider', 'openai')}")
                print(f"   Model: {settings.get('translation_model', 'gpt-4o-mini')}")
        except Exception as e:
            print(f"Error loading settings: {e}")

    connected = await connect_to_database()
    if not connected:
        print("Application running in limited mode (no database)")
    yield
    await close_database_connection()


app = FastAPI(
    title="SRT Comparison API",
    description="Compare SRT subtitle files and track comparison history",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== Health Check ==============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected" if is_database_available() else "unavailable",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============== Clear Cache ==============

@app.post("/api/clear-cache")
async def clear_translation_cache():
    _require_db()
    try:
        count = await clear_all_translations()
        return {"message": f"Cache cleared successfully. Deleted {count} translations."}
    except HTTPException:
        raise
    except Exception as e:
        _db_error("clear translation cache", e)


# ============== Translation ==============

@app.post("/api/translate")
async def translate_srt_file(
    file: UploadFile,
    target_lang: str = Form(..., description="Target language code"),
    save_history: bool = Form(True),
    use_cache: bool = Form(True),
):
    if not file.filename or not file.filename.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Only .srt files allowed.")
    path = None
    try:
        content = await file.read()
        source_hash = hashlib.sha256(content).hexdigest()
        user_id = "anonymous"
        target_lang_norm = (target_lang or "").strip().lower() or "en"

        translation_id = None
        if is_database_available() and use_cache:
            cached = await find_cached_translation(user_id, source_hash, target_lang_norm)
            if cached and cached.get("output_srt"):
                translation_id = str(cached["id"])
                out_content = cached["output_srt"]
                print(f"CACHE HIT: {file.filename} -> {target_lang_norm}")
                fname = file.filename.replace(".srt", "") + f" - {target_lang_norm}.srt"
                return StreamingResponse(
                    io.BytesIO(out_content.encode("utf-8")),
                    media_type="application/x-subrip; charset=utf-8",
                    headers={
                        "Content-Disposition": f'attachment; filename="{fname}"',
                        "X-Translation-Id": translation_id,
                        "X-Translation-Cache": "HIT",
                    },
                )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".srt") as tmp:
            tmp.write(content)
            path = tmp.name
        print(f"Translating {file.filename} to {target_lang_norm}...")
        translate_fn = get_translator(target_lang_norm)
        out_content = translate_srt_content(path, translate_fn)
        print(f"Translation complete. Output size: {len(out_content)} chars")

        if is_database_available() and save_history:
            try:
                translation_id = await insert_translation(
                    user_id, file.filename, source_hash,
                    target_lang_norm, out_content, datetime.utcnow(),
                )
            except Exception as db_err:
                print(f"Could not save translation: {db_err}")

        fname = file.filename.replace(".srt", "") + f" - {target_lang_norm}.srt"
        return StreamingResponse(
            io.BytesIO(out_content.encode("utf-8")),
            media_type="application/x-subrip; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Translation-Id": translation_id or "",
                "X-Translation-Cache": "MISS" if use_cache else "BYPASS",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


@app.get("/api/translations")
async def list_translations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    _require_db()
    try:
        rows = await list_translations_db("anonymous", skip, limit)
        return [
            {"id": str(r["id"]), "source_filename": r.get("source_filename"),
             "target_lang": r.get("target_lang"), "created_at": r.get("created_at")}
            for r in rows
        ]
    except HTTPException:
        raise
    except Exception as e:
        _db_error("list translations", e)


@app.get("/api/translations/{translation_id}/download")
async def download_translation(translation_id: str):
    _require_db()
    if not _valid_id(translation_id):
        raise HTTPException(status_code=400, detail="Invalid translation ID")
    try:
        doc = await get_translation_by_id(translation_id, "anonymous")
        if not doc:
            raise HTTPException(status_code=404, detail="Translation not found")
        fname = (doc.get("source_filename") or f"translation_{translation_id}.srt").replace(".srt", "")
        fname = f"{fname} - {doc.get('target_lang','')}.srt"
        return StreamingResponse(
            io.BytesIO((doc.get("output_srt") or "").encode("utf-8")),
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        _db_error("download translation", e)


@app.delete("/api/translations/{translation_id}")
async def delete_translation(translation_id: str):
    _require_db()
    if not _valid_id(translation_id):
        raise HTTPException(status_code=400, detail="Invalid translation ID")
    try:
        count = await delete_translation_db(translation_id, "anonymous")
        if count == 0:
            raise HTTPException(status_code=404, detail="Translation not found")
        return {"message": "Translation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        _db_error("delete translation", e)


# ============== Comparison ==============

@app.post("/api/compare")
async def compare_srt_files(
    file1: UploadFile,
    file2: UploadFile,
    time_tolerance_ms: int = Form(0),
    shift_window_ms: int = Form(30000),
    lookahead: int = Form(300),
    normalize_dialogue: bool = Form(True),
    save_history: bool = Form(True),
):
    ALLOWED_SUBTITLE_EXTS = {'.srt', '.asc'}
    for f in [file1, file2]:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_SUBTITLE_EXTS:
            raise HTTPException(status_code=400, detail=f"Invalid file: {f.filename}. Only .srt and .asc allowed.")

    path1 = path2 = None
    try:
        ext1 = os.path.splitext(file1.filename)[1].lower() or '.srt'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext1) as tmp1:
            tmp1.write(await file1.read())
            path1 = tmp1.name
        ext2 = os.path.splitext(file2.filename)[1].lower() or '.srt'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext2) as tmp2:
            tmp2.write(await file2.read())
            path2 = tmp2.name

        res = compare_srts(
            path1, path2,
            time_tolerance_ms=time_tolerance_ms,
            shift_window_ms=shift_window_ms,
            lookahead=lookahead,
            normalize_dialogue=normalize_dialogue,
        )
        json_result = results_to_json(res)

        comparison_id = None
        if save_history and is_database_available():
            try:
                comparison_id = await insert_comparison(
                    "anonymous", file1.filename, file2.filename,
                    json_result, "completed", datetime.utcnow(),
                )
            except Exception as db_err:
                print(f"Could not save comparison: {db_err}")

        return {"comparison_id": comparison_id, **json_result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing files: {str(e)}")
    finally:
        for p in [path1, path2]:
            if p and os.path.exists(p):
                os.unlink(p)


@app.get("/api/comparisons", response_model=List[ComparisonResponse])
async def get_comparisons(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    _require_db()
    try:
        rows = await get_comparisons_list("anonymous", skip, limit)
        comparisons = []
        for row in rows:
            results = _parse_results(row)
            sd = results.get("summary", {})
            matches = sd.get("matches", 0)
            time_diffs = sd.get("time_differences", 0)
            dialogue_diffs = sd.get("dialogue_differences", 0)
            additions = sd.get("additions", 0)
            removals = sd.get("removals", 0)
            tf1 = sd.get("total_file1", matches + time_diffs + dialogue_diffs + removals)
            tf2 = sd.get("total_file2", matches + time_diffs + dialogue_diffs + additions)
            te = max(tf1, tf2, 1)
            mp = sd.get("match_percentage", round((matches / te) * 100, 2))
            summary = ComparisonSummary(
                total_file1=tf1, total_file2=tf2,
                matches=matches, time_differences=time_diffs,
                dialogue_differences=dialogue_diffs,
                additions=additions, removals=removals,
                match_percentage=mp,
            )
            comparisons.append(ComparisonResponse(
                id=str(row["id"]),
                file1_name=row["file1_name"],
                file2_name=row["file2_name"],
                summary=summary,
                status=row.get("status", "completed"),
                created_at=row["created_at"],
            ))
        return comparisons
    except HTTPException:
        raise
    except Exception as e:
        _db_error("fetch comparisons", e)


@app.get("/api/comparisons/{comparison_id}")
async def get_comparison(comparison_id: str):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        row = await get_comparison_by_id(comparison_id, "anonymous")
        if not row:
            raise HTTPException(status_code=404, detail="Comparison not found")
        return {
            "id": str(row["id"]),
            "file1_name": row["file1_name"],
            "file2_name": row["file2_name"],
            "results": _parse_results(row),
            "status": row.get("status", "completed"),
            "created_at": row["created_at"],
        }
    except HTTPException:
        raise
    except Exception as e:
        _db_error("fetch comparison detail", e)


@app.get("/api/comparisons/{comparison_id}/export")
async def export_comparison(
    comparison_id: str,
    format: str = Query("json", regex="^(json|csv)$"),
):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        row = await get_comparison_by_id(comparison_id, "anonymous")
        if not row:
            raise HTTPException(status_code=404, detail="Comparison not found")
        results = _parse_results(row)
        filename = f"comparison_{comparison_id}"
        if format == "csv":
            csv_content = results_to_csv(results)
            return StreamingResponse(
                io.StringIO(csv_content), media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
            )
        else:
            json_content = json_mod.dumps(results, indent=2, default=str)
            return StreamingResponse(
                io.StringIO(json_content), media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}.json"},
            )
    except HTTPException:
        raise
    except Exception as e:
        _db_error("export comparison", e)


@app.get("/api/comparisons/{comparison_id}/download-srt")
async def download_bilingual_srt(comparison_id: str):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        row = await get_comparison_by_id(comparison_id, "anonymous")
        if not row:
            raise HTTPException(status_code=404, detail="Comparison not found")
        results = _parse_results(row)
        srt_content = generate_bilingual_srt(results)
        fname = f"{row['file2_name'].replace('.srt', '')}_bilingual.srt"
        return StreamingResponse(
            io.StringIO(srt_content), media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        _db_error("download bilingual SRT", e)


@app.put("/api/comparisons/{comparison_id}/results")
async def update_comparison_results(comparison_id: str, results: dict):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        count = await update_comparison_results_db(comparison_id, "anonymous", results, datetime.utcnow())
        if count == 0:
            raise HTTPException(status_code=404, detail="Comparison not found")
        return {"message": "Comparison updated successfully", "id": comparison_id}
    except HTTPException:
        raise
    except Exception as e:
        _db_error("update comparison results", e)


@app.patch("/api/comparisons/{comparison_id}/status")
async def update_comparison_status(
    comparison_id: str,
    new_status: str = Form(..., regex="^(completed|processing|failed)$"),
):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        count = await update_comparison_status_db(comparison_id, "anonymous", new_status)
        if count == 0:
            raise HTTPException(status_code=404, detail="Comparison not found")
        return {"message": f"Status updated to {new_status}", "status": new_status}
    except HTTPException:
        raise
    except Exception as e:
        _db_error("update comparison status", e)


@app.delete("/api/comparisons/{comparison_id}")
async def delete_comparison(comparison_id: str):
    _require_db()
    if not _valid_id(comparison_id):
        raise HTTPException(status_code=400, detail="Invalid comparison ID")
    try:
        count = await delete_comparison_db(comparison_id, "anonymous")
        if count == 0:
            raise HTTPException(status_code=404, detail="Comparison not found")
        return {"message": "Comparison deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        _db_error("delete comparison", e)


# ============== Settings ==============

def _settings_path():
    d = pathlib.Path.home() / ".srt_compare"
    d.mkdir(exist_ok=True)
    return str(d / "app_settings.json")

SETTINGS_FILE = _settings_path()


@app.get("/api/models")
async def get_available_models():
    """Return available models for each AI provider."""
    from translator import MODELS
    return MODELS


@app.get("/api/settings")
async def get_settings():
    defaults = {
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""), 
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "claude_api_key": os.environ.get("CLAUDE_API_KEY", ""),
        "translation_provider": os.environ.get("TRANSLATION_PROVIDER", "openai"),
        "translation_model": os.environ.get("TRANSLATION_MODEL", "gpt-4o-mini")
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                defaults.update(json_mod.load(f))
        except Exception:
            pass
    return defaults


@app.post("/api/settings")
async def save_settings(
    openai_api_key: str = Form(""), 
    gemini_api_key: str = Form(""),
    claude_api_key: str = Form(""),
    translation_provider: str = Form("openai"),
    translation_model: str = Form("gpt-4o-mini")
):
    settings = {
        "openai_api_key": openai_api_key, 
        "gemini_api_key": gemini_api_key,
        "claude_api_key": claude_api_key,
        "translation_provider": translation_provider,
        "translation_model": translation_model
    }
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json_mod.dump(settings, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")
        
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key
    if gemini_api_key:
        os.environ["GEMINI_API_KEY"] = gemini_api_key
    if claude_api_key:
        os.environ["CLAUDE_API_KEY"] = claude_api_key
    if translation_provider:
        os.environ["TRANSLATION_PROVIDER"] = translation_provider
    if translation_model:
        os.environ["TRANSLATION_MODEL"] = translation_model
        
    return {"message": "Settings saved successfully", "settings": settings}


# ============== Static Frontend ==============

def _get_static_dir():
    if getattr(sys, 'frozen', False):
        # PyInstaller bundle — check _MEIPASS first (onefile), then _internal (onedir), then exe dir
        candidates = []
        if hasattr(sys, '_MEIPASS'):
            candidates.append(pathlib.Path(sys._MEIPASS) / "static")
        exe_dir = pathlib.Path(sys.executable).parent
        candidates.append(exe_dir / "_internal" / "static")
        candidates.append(exe_dir / "static")
        for c in candidates:
            if c.exists():
                return c
        return candidates[-1]  # fallback
    else:
        return pathlib.Path(__file__).parent / "static"

STATIC_DIR = _get_static_dir()


@app.get("/")
async def serve_frontend():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "SRT Compare API running. Frontend not found at " + str(index_file)}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
