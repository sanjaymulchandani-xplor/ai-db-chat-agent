from __future__ import annotations

import base64
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

"""Encrypted BYOK secrets store (SQLite + Fernet).

Stores OpenAI API key and Postgres connection string encrypted at rest.
Unlock with a master passphrase (never stored; used to derive the Fernet key).
"""

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = SCRIPT_DIR / "database" / "app_secrets.db"

SECRET_KEYS = ("openai_api_key", "connection_string")
_VERIFIER_PLAINTEXT = "mariana-chat-tool-ok"
_KDF_ITERATIONS = 390_000


def get_db_path() -> Path:
    override = os.environ.get("APP_SECRETS_DB")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS secrets_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            salt BLOB NOT NULL,
            verifier BLOB NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_secrets (
            key TEXT PRIMARY KEY,
            ciphertext BLOB NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_fernet(passphrase: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def is_initialized(*, db_path: Optional[Path] = None) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM secrets_meta WHERE id = 1").fetchone()
        return row is not None


def initialize_secrets(
    passphrase: str,
    openai_api_key: str,
    connection_string: str,
    *,
    db_path: Optional[Path] = None,
) -> None:
    """First-time setup: create salt + encrypt secrets. Fails if already initialized."""
    if not passphrase or len(passphrase) < 8:
        raise ValueError("Master passphrase must be at least 8 characters.")
    if not openai_api_key.strip():
        raise ValueError("OpenAI API key is required.")
    if not connection_string.strip():
        raise ValueError("Postgres connection string is required.")
    if is_initialized(db_path=db_path):
        raise ValueError("Secrets already initialized. Unlock and update instead.")

    salt = os.urandom(16)
    fernet = _derive_fernet(passphrase, salt)
    verifier = fernet.encrypt(_VERIFIER_PLAINTEXT.encode("utf-8"))
    now = _utc_now()

    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO secrets_meta (id, salt, verifier, created_at) VALUES (1, ?, ?, ?)",
            (salt, verifier, now),
        )
        for key, value in (
            ("openai_api_key", openai_api_key.strip()),
            ("connection_string", connection_string.strip()),
        ):
            conn.execute(
                """
                INSERT INTO app_secrets (key, ciphertext, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, fernet.encrypt(value.encode("utf-8")), now),
            )
        conn.commit()


def unlock(passphrase: str, *, db_path: Optional[Path] = None) -> Fernet:
    """Validate passphrase and return a Fernet instance for decrypt/encrypt."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT salt, verifier FROM secrets_meta WHERE id = 1"
        ).fetchone()
        if not row:
            raise ValueError("Secrets not initialized. Complete setup first.")
        fernet = _derive_fernet(passphrase, row["salt"])
        try:
            plain = fernet.decrypt(row["verifier"]).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Incorrect master passphrase.") from exc
        if plain != _VERIFIER_PLAINTEXT:
            raise ValueError("Incorrect master passphrase.")
        return fernet


def load_secrets(fernet: Fernet, *, db_path: Optional[Path] = None) -> Dict[str, str]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT key, ciphertext FROM app_secrets").fetchall()
    out: Dict[str, str] = {}
    for row in rows:
        try:
            out[row["key"]] = fernet.decrypt(row["ciphertext"]).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt secrets (wrong passphrase?).") from exc
    for required in SECRET_KEYS:
        if not out.get(required):
            raise ValueError(f"Missing secret: {required}")
    return out


def save_secrets(
    fernet: Fernet,
    *,
    openai_api_key: Optional[str] = None,
    connection_string: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Update one or both secrets (must already be unlocked/initialized)."""
    updates = {}
    if openai_api_key is not None and openai_api_key.strip():
        updates["openai_api_key"] = openai_api_key.strip()
    if connection_string is not None and connection_string.strip():
        updates["connection_string"] = connection_string.strip()
    if not updates:
        raise ValueError("Nothing to update.")

    now = _utc_now()
    with _connect(db_path) as conn:
        if not conn.execute("SELECT 1 FROM secrets_meta WHERE id = 1").fetchone():
            raise ValueError("Secrets not initialized.")
        for key, value in updates.items():
            conn.execute(
                """
                INSERT INTO app_secrets (key, ciphertext, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    updated_at = excluded.updated_at
                """,
                (key, fernet.encrypt(value.encode("utf-8")), now),
            )
        conn.commit()


def reset_all(*, db_path: Optional[Path] = None) -> None:
    """Delete all encrypted secrets (destructive)."""
    path = db_path or get_db_path()
    if path.exists():
        path.unlink()
