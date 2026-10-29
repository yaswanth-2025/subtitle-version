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
from fastapi.concurrency import run_in_threadpool
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
import database as dbm
from srt_compare import parse_subtitle, select_compare_text, compare_srts, results_to_json, results_to_csv, translate_srt_content, generate_bilingual_srt
from translator import get_translator


# --- helpers ---

def _require_db():
    """Raise a JSON-friendly 503 if the database is not available."""
    if not is_database_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available."
        )


def _attachment_header(filename: str) -> str:
    """Content-Disposition safe for spaces, commas, '&' and non-ASCII (e.g. Arabic) names."""
    from urllib.parse import quote
    ascii_name = "".join(c if c.isascii() and c not in '",;\\' else "_" for c in filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


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
    compare_mode: str = Form("full"),
    compare_mode2: Optional[str] = Form(None),
    save_history: bool = Form(True),
):
    ALLOWED_SUBTITLE_EXTS = {'.srt', '.asc'}
    for f in [file1, file2]:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_SUBTITLE_EXTS:
            raise HTTPException(status_code=400, detail=f"Invalid file: {f.filename}. Only .srt and .asc allowed.")

    modes = ("english", "first_half", "second_half", "full")
    if compare_mode not in modes or (compare_mode2 is not None and compare_mode2 not in modes):
        raise HTTPException(status_code=400, detail="compare_mode must be english, first_half, second_half or full")

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
            compare_mode=compare_mode,
            compare_mode2=compare_mode2,
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
        fname = f"{os.path.splitext(row['file2_name'])[0]}_bilingual.srt"
        return StreamingResponse(
            io.BytesIO(srt_content.encode("utf-8")), media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(fname)},
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


# ============== Movies (folder per movie, versions inside) ==============

_SUBTITLE_EXTS = {'.srt', '.asc'}
_COMPARE_MODES = ("english", "first_half", "second_half", "full")


def _summary_of(row):
    sd = _parse_results(row).get("summary", {})
    return {
        "matches": sd.get("matches", 0),
        "match_percentage": sd.get("match_percentage", 0),
        "total_file1": sd.get("total_file1", 0),
        "total_file2": sd.get("total_file2", 0),
    }


async def _movie_or_404(movie_id):
    _require_db()
    movie = await dbm.get_movie_db(movie_id, "anonymous")
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


@app.get("/api/movies")
async def list_movies():
    _require_db()
    return await dbm.list_movies_db("anonymous")


@app.post("/api/movies")
async def create_movie(name: str = Form(...)):
    _require_db()
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Movie name is required")
    movie_id = await dbm.create_movie_db("anonymous", name)
    if movie_id is None:
        raise HTTPException(status_code=409, detail=f"A movie named '{name}' already exists")
    return {"id": movie_id, "name": name}


@app.get("/api/movies/{movie_id}")
async def get_movie(movie_id: int):
    movie = await _movie_or_404(movie_id)
    versions = await dbm.list_versions_db(movie_id)
    comparisons = []
    for row in await dbm.get_movie_comparisons_db(movie_id):
        comparisons.append({
            "id": row["id"],
            "file1_name": row["file1_name"],
            "file2_name": row["file2_name"],
            "status": row.get("status", "completed"),
            "created_at": row["created_at"],
            **_summary_of(row),
        })
    return {**movie, "versions": versions, "comparisons": comparisons}


@app.delete("/api/movies/{movie_id}")
async def delete_movie(movie_id: int):
    await _movie_or_404(movie_id)
    await dbm.delete_movie_db(movie_id, "anonymous")
    return {"deleted": True}


@app.post("/api/movies/{movie_id}/versions")
async def add_movie_version(movie_id: int, file: UploadFile, label: str = Form("")):
    await _movie_or_404(movie_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _SUBTITLE_EXTS:
        raise HTTPException(status_code=400, detail="Only .srt and .asc files are allowed.")
    content = await file.read()
    if not content.strip():
        raise HTTPException(status_code=400, detail="File is empty")
    label = label.strip() or os.path.splitext(file.filename)[0]
    version_id = await dbm.add_version_db(movie_id, label, file.filename, content)
    return {"id": version_id, "label": label, "filename": file.filename}


@app.delete("/api/movies/{movie_id}/versions/{version_id}")
async def delete_movie_version(movie_id: int, version_id: int):
    await _movie_or_404(movie_id)
    if not await dbm.delete_version_db(movie_id, version_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return {"deleted": True}


def _version_segments(version):
    """Parse a stored version into ordered segments, without touching the stored file."""
    ext = os.path.splitext(version["filename"])[1].lower() or '.srt'
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(version["content"])
        path = tmp.name
    try:
        return parse_subtitle(path)
    finally:
        os.unlink(path)


async def _version_or_404(movie_id, version_id):
    version = await dbm.get_version_db(movie_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


@app.get("/api/movies/{movie_id}/versions/{version_id}/segments")
async def get_version_segments(movie_id: int, version_id: int):
    await _movie_or_404(movie_id)
    version = await _version_or_404(movie_id, version_id)
    segs = _version_segments(version)
    return {
        "version": {"id": version["id"], "label": version["label"], "filename": version["filename"]},
        "segments": [
            {"ord": i, "index": s["index"], "start": s["start"], "end": s["end"], "text": s["text"]}
            for i, s in enumerate(segs)
        ],
        "draft": await dbm.get_draft_db(version_id),
    }


@app.put("/api/movies/{movie_id}/versions/{version_id}/draft")
async def save_version_draft(movie_id: int, version_id: int, body: dict):
    """Autosave in-progress edits against this version (the version itself is unchanged)."""
    await _movie_or_404(movie_id)
    await _version_or_404(movie_id, version_id)
    items = {str(k): str(v or "") for k, v in (body.get("items") or {}).items()}
    if not items:
        await dbm.delete_draft_db(version_id)
    else:
        await dbm.save_draft_db(version_id, {"items": items, "label": str(body.get("label") or "")})
    return {"saved": len(items)}


@app.delete("/api/movies/{movie_id}/versions/{version_id}/draft")
async def discard_version_draft(movie_id: int, version_id: int):
    await _movie_or_404(movie_id)
    await _version_or_404(movie_id, version_id)
    await dbm.delete_draft_db(version_id)
    return {"deleted": True}


@app.get("/api/movies/{movie_id}/versions/{version_id}/download")
async def download_version(movie_id: int, version_id: int):
    await _movie_or_404(movie_id)
    version = await _version_or_404(movie_id, version_id)
    from urllib.parse import quote
    return StreamingResponse(
        io.BytesIO(version["content"]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(version['filename'])}"},
    )


@app.post("/api/movies/{movie_id}/versions/{version_id}/edit")
async def save_edited_version(movie_id: int, version_id: int, body: dict):
    """Save edited subtitle text as the next version in the movie folder."""
    movie = await _movie_or_404(movie_id)
    version = await _version_or_404(movie_id, version_id)
    segs = _version_segments(version)
    edits = body.get("items") or {}
    blocks = []
    for i, s in enumerate(segs):
        text = str(edits.get(str(i), s["text"]) or "").strip()
        if not text:
            continue  # a cleared row removes that subtitle from the new version
        blocks.append(f"{len(blocks) + 1}\n{s['start']} --> {s['end']}\n{text}\n")
    if not blocks:
        raise HTTPException(status_code=400, detail="Nothing to save: all subtitles are empty")
    content = ("\n".join(blocks)).encode("utf-8")
    label = (body.get("label") or "").strip() or f"{version['label']} (edited)"
    base_name = os.path.splitext(version["filename"])[0]
    filename = f"{base_name}_edited.srt"
    new_id = await dbm.add_version_db(movie["id"], label, filename, content)
    await dbm.delete_draft_db(version_id)
    return {"id": new_id, "label": label, "filename": filename}


@app.post("/api/movies/{movie_id}/versions/{version_id}/translate")
async def translate_version_rows(
    movie_id: int,
    version_id: int,
    lang: str = Form("fr"),
    ord: Optional[int] = Form(None),
):
    """Auto-translate rows with the configured LLM. Nothing is saved; the editor reviews it first."""
    await _movie_or_404(movie_id)
    version = await _version_or_404(movie_id, version_id)
    segs = _version_segments(version)
    targets = [ord] if ord is not None else list(range(len(segs)))
    if any(i < 0 or i >= len(segs) for i in targets):
        raise HTTPException(status_code=400, detail="Invalid segment")
    translate_fn = get_translator((lang or "fr").strip().lower())

    def _run():
        out = {}
        for i in targets:
            src = select_compare_text(segs[i], "second_half")
            if src.strip():
                out[i] = translate_fn(src)
        return out

    try:
        translated = await run_in_threadpool(_run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")
    return {"translated": {str(k): v for k, v in translated.items()}}


@app.post("/api/movies/{movie_id}/compare")
async def compare_movie_versions(
    movie_id: int,
    version1_id: int = Form(...),
    version2_id: int = Form(...),
    compare_mode: str = Form("full"),
    compare_mode2: Optional[str] = Form(None),
):
    await _movie_or_404(movie_id)
    if compare_mode not in _COMPARE_MODES or (compare_mode2 is not None and compare_mode2 not in _COMPARE_MODES):
        raise HTTPException(status_code=400, detail="compare_mode must be english, first_half, second_half or full")
    v1 = await dbm.get_version_db(movie_id, version1_id)
    v2 = await dbm.get_version_db(movie_id, version2_id)
    if not v1 or not v2:
        raise HTTPException(status_code=404, detail="Version not found")

    paths = []
    try:
        for v in (v1, v2):
            ext = os.path.splitext(v["filename"])[1].lower() or '.srt'
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(v["content"])
                paths.append(tmp.name)
        res = compare_srts(
            paths[0], paths[1], lookahead=300,
            compare_mode=compare_mode, compare_mode2=compare_mode2,
        )
        json_result = results_to_json(res)
        comparison_id = await dbm.insert_comparison(
            "anonymous", v1["label"], v2["label"], json_result,
            "completed", datetime.utcnow(), movie_id=movie_id,
        )
        return {"comparison_id": comparison_id, **json_result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing versions: {str(e)}")
    finally:
        for p in paths:
            if os.path.exists(p):
                os.unlink(p)


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
