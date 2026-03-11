"""
SQLite database connection and initialization.

Zero-config, file-based database - no external server needed.
Data stored in ~/.srt_compare/srt_compare.db
"""

import aiosqlite
import os
import json
import pathlib
from typing import Optional
from datetime import datetime

# Database path - user's home directory
_home = pathlib.Path.home()
_db_dir = _home / ".srt_compare"
_db_dir.mkdir(exist_ok=True)
DB_PATH = str(_db_dir / "srt_compare.db")

# Global connection
_db: Optional[aiosqlite.Connection] = None


async def connect_to_database():
    """Open SQLite database and create tables. Returns True on success."""
    global _db
    try:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")

        await _db.execute("""
            CREATE TABLE IF NOT EXISTS comparisons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                file1_name TEXT NOT NULL,
                file2_name TEXT NOT NULL,
                results TEXT DEFAULT '{}',
                status TEXT DEFAULT 'completed',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source_filename TEXT,
                source_hash TEXT,
                target_lang TEXT,
                output_srt TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await _db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_translations_cache
            ON translations(user_id, source_hash, target_lang)
        """)
        await _db.commit()
        print(f"Connected to SQLite database: {DB_PATH}")
        return True
    except Exception as e:
        print(f"Failed to connect to SQLite: {e}")
        _db = None
        return False


async def close_database_connection():
    """Close the SQLite connection."""
    global _db
    if _db:
        try:
            await _db.close()
        except Exception:
            pass
        _db = None
    print("SQLite connection closed")


def is_database_available():
    """Check if the database connection is active."""
    return _db is not None


# ============== Comparison helpers ==============

async def insert_comparison(user_id, file1_name, file2_name, results, status, created_at):
    """Insert a new comparison. Returns the new row ID as a string."""
    results_json = json.dumps(results, default=str) if not isinstance(results, str) else results
    ts = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
    cursor = await _db.execute(
        "INSERT INTO comparisons (user_id, file1_name, file2_name, results, status, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, file1_name, file2_name, results_json, status, ts),
    )
    await _db.commit()
    return str(cursor.lastrowid)


async def get_comparisons_list(user_id, skip=0, limit=20):
    """Return a list of comparisons (most recent first)."""
    cursor = await _db.execute(
        "SELECT * FROM comparisons WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user_id, limit, skip),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_comparison_by_id(comparison_id, user_id):
    """Return a single comparison or None."""
    cursor = await _db.execute(
        "SELECT * FROM comparisons WHERE id=? AND user_id=?",
        (int(comparison_id), user_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_comparison_results_db(comparison_id, user_id, results, updated_at):
    """Update the results JSON blob. Returns number of rows affected."""
    results_json = json.dumps(results, default=str) if not isinstance(results, str) else results
    ts = updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)
    cursor = await _db.execute(
        "UPDATE comparisons SET results=?, updated_at=? WHERE id=? AND user_id=?",
        (results_json, ts, int(comparison_id), user_id),
    )
    await _db.commit()
    return cursor.rowcount


async def update_comparison_status_db(comparison_id, user_id, new_status):
    """Update comparison status. Returns number of rows affected."""
    cursor = await _db.execute(
        "UPDATE comparisons SET status=? WHERE id=? AND user_id=?",
        (new_status, int(comparison_id), user_id),
    )
    await _db.commit()
    return cursor.rowcount


async def delete_comparison_db(comparison_id, user_id):
    """Delete a comparison. Returns number of rows affected."""
    cursor = await _db.execute(
        "DELETE FROM comparisons WHERE id=? AND user_id=?",
        (int(comparison_id), user_id),
    )
    await _db.commit()
    return cursor.rowcount


# ============== Translation helpers ==============

async def find_cached_translation(user_id, source_hash, target_lang):
    """Find a cached translation by hash+lang. Returns dict or None."""
    cursor = await _db.execute(
        "SELECT * FROM translations WHERE user_id=? AND source_hash=? AND target_lang=?",
        (user_id, source_hash, target_lang),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def insert_translation(user_id, source_filename, source_hash, target_lang, output_srt, created_at):
    """Insert or replace a translation. Returns the row ID as a string."""
    ts = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
    cursor = await _db.execute(
        """INSERT OR REPLACE INTO translations
           (user_id, source_filename, source_hash, target_lang, output_srt, created_at)
           VALUES (?,?,?,?,?,?)""",
        (user_id, source_filename, source_hash, target_lang, output_srt, ts),
    )
    await _db.commit()
    return str(cursor.lastrowid)


async def list_translations_db(user_id, skip=0, limit=20):
    """List translations (most recent first)."""
    cursor = await _db.execute(
        "SELECT id, user_id, source_filename, target_lang, created_at FROM translations WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user_id, limit, skip),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_translation_by_id(translation_id, user_id):
    """Fetch a single translation. Returns dict or None."""
    cursor = await _db.execute(
        "SELECT * FROM translations WHERE id=? AND user_id=?",
        (int(translation_id), user_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_translation_db(translation_id, user_id):
    """Delete a translation. Returns number of rows affected."""
    cursor = await _db.execute(
        "DELETE FROM translations WHERE id=? AND user_id=?",
        (int(translation_id), user_id),
    )
    await _db.commit()
    return cursor.rowcount


async def clear_all_translations():
    """Delete all translations (cache clear). Returns count deleted."""
    cursor = await _db.execute("SELECT COUNT(*) as cnt FROM translations")
    row = await cursor.fetchone()
    count = row["cnt"] if row else 0
    await _db.execute("DELETE FROM translations")
    await _db.commit()
    return count
