from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

"""SQLite persistence for chat session memory."""


SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = SCRIPT_DIR / "database" / "session_memory.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> Path:
    override = os.environ.get("SESSION_MEMORY_DB")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            schema_name TEXT NOT NULL,
            entities_json TEXT NOT NULL DEFAULT '{}',
            last_question TEXT,
            last_sql TEXT,
            last_answer_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sql_text TEXT,
            answer_summary TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
        );

        CREATE INDEX IF NOT EXISTS idx_chat_turns_session
            ON chat_turns(session_id, id);
        """
    )
    conn.commit()


def upsert_session(
    session_id: str,
    schema_name: str,
    entities: Dict[str, Any],
    last_question: Optional[str] = None,
    last_sql: Optional[str] = None,
    last_answer_summary: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> None:
    now = _utc_now()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT created_at FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        created = row["created_at"] if row else now
        conn.execute(
            """
            INSERT INTO chat_sessions (
                session_id, schema_name, entities_json,
                last_question, last_sql, last_answer_summary,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                schema_name = excluded.schema_name,
                entities_json = excluded.entities_json,
                last_question = excluded.last_question,
                last_sql = excluded.last_sql,
                last_answer_summary = excluded.last_answer_summary,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                schema_name,
                json.dumps(entities),
                last_question,
                last_sql,
                last_answer_summary,
                created,
                now,
            ),
        )
        conn.commit()


def append_turn(
    session_id: str,
    role: str,
    content: str,
    *,
    sql_text: Optional[str] = None,
    answer_summary: Optional[str] = None,
    error_text: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_turns (
                session_id, role, content, sql_text, answer_summary, error_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                sql_text,
                answer_summary,
                error_text,
                _utc_now(),
            ),
        )
        conn.commit()


def clear_session_turns(session_id: str, *, db_path: Optional[Path] = None) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM chat_turns WHERE session_id = ?", (session_id,))
        conn.execute(
            """
            UPDATE chat_sessions
            SET entities_json = '{}',
                last_question = NULL,
                last_sql = NULL,
                last_answer_summary = NULL,
                updated_at = ?
            WHERE session_id = ?
            """,
            (_utc_now(), session_id),
        )
        conn.commit()


def list_sessions(*, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.session_id,
                s.schema_name,
                s.entities_json,
                s.last_question,
                s.created_at,
                s.updated_at,
                (SELECT COUNT(*) FROM chat_turns t WHERE t.session_id = s.session_id) AS turn_count
            FROM chat_sessions s
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: str, *, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def get_turns(session_id: str, *, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, sql_text, answer_summary, error_text, created_at
            FROM chat_turns
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
