from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from memory import store as memory_store

"""In-process session memory for Text-to-SQL follow-ups (should be converted to a proper vector memory with auth of Mariana).

Keyed by session_id only, no user auth. Prompt context is in-process;
turns are also persisted to SQLite so `read_memory.py` can inspect them.
"""


MAX_TURNS = 5  # compact user/assistant pairs kept for the prompt
MAX_SQL_CHARS = 500
MAX_ANSWER_CHARS = 280

_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
)
_LOCATION_ID_RE = re.compile(
    r"\blocation(?:\s+id)?\s*[:=]?\s*(\d+)\b", re.IGNORECASE
)
_USER_ID_RE = re.compile(r"\buser(?:\s+id)?\s*[:=]?\s*(\d+)\b", re.IGNORECASE)
_SQL_EMAIL_RE = re.compile(
    r"['\"]([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})['\"]"
)
_SQL_LOCATION_ID_RE = re.compile(
    r"\blocation(?:_id)?\s*=\s*(\d+)\b", re.IGNORECASE
)
_SQL_USER_ID_RE = re.compile(
    r"\b(?:user_id|booked_on_behalf_of_user_id)\s*=\s*(\d+)\b",
    re.IGNORECASE,
)

# Column names (normalized) > entity keys when reading query results
_RESULT_COLUMN_MAP = {
    "email": "email",
    "user_email": "email",
    "guest_email": "email",
    "user_id": "user_id",
    "full_name": "full_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "location_id": "location_id",
    "location_name": "location_name",
}


@dataclass
class SessionMemory:
    """Short-term chat memory for one CLI session."""

    schema_name: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entities: Dict[str, Any] = field(default_factory=dict)
    last_question: Optional[str] = None
    last_sql: Optional[str] = None
    last_answer_summary: Optional[str] = None
    turns: List[Dict[str, str]] = field(default_factory=list)
    persist: bool = True

    def __post_init__(self) -> None:
        if self.persist:
            self._save_session()

    def clear(self) -> None:
        """Wipe entities and turns; keep session_id and schema."""
        self.entities.clear()
        self.last_question = None
        self.last_sql = None
        self.last_answer_summary = None
        self.turns.clear()
        if self.persist:
            memory_store.clear_session_turns(self.session_id)
            self._save_session()

    def reset(self) -> None:
        """New session_id and empty memory (still same schema)."""
        self.session_id = str(uuid.uuid4())
        self.entities.clear()
        self.last_question = None
        self.last_sql = None
        self.last_answer_summary = None
        self.turns.clear()
        if self.persist:
            self._save_session()

    def extract_entities(self, question: str, sql: Optional[str] = None) -> None:
        """Update known slots from the user question and/or generated SQL."""
        email = _EMAIL_RE.search(question)
        if email:
            self.entities["email"] = email.group(1).lower()

        loc = _LOCATION_ID_RE.search(question)
        if loc:
            self.entities["location_id"] = int(loc.group(1))

        user = _USER_ID_RE.search(question)
        if user:
            self.entities["user_id"] = int(user.group(1))

        if not sql:
            return

        sql_email = _SQL_EMAIL_RE.search(sql)
        if sql_email:
            self.entities["email"] = sql_email.group(1).lower()

        sql_loc = _SQL_LOCATION_ID_RE.search(sql)
        if sql_loc:
            self.entities["location_id"] = int(sql_loc.group(1))

        sql_user = _SQL_USER_ID_RE.search(sql)
        if sql_user:
            self.entities["user_id"] = int(sql_user.group(1))

    def ingest_answer_text(self, answer: Optional[str]) -> None:
        """Pull emails (and similar) out of the NL answer."""
        if not answer:
            return
        email = _EMAIL_RE.search(answer)
        if email:
            self.entities["email"] = email.group(1).lower()

    def ingest_result_rows(
        self,
        columns: Optional[List[str]],
        rows: Optional[List[Any]],
    ) -> None:
        """Update entities from the first result row (e.g. after 'top user' queries)."""
        if not columns or not rows:
            return
        row = rows[0]
        if row is None:
            return
        # psycopg2 rows may be tuples
        values = list(row)
        for col, value in zip(columns, values):
            if value is None:
                continue
            key = _RESULT_COLUMN_MAP.get(str(col).strip().lower())
            if not key:
                continue
            if key == "email":
                self.entities["email"] = str(value).lower()
            elif key == "user_id":
                try:
                    self.entities["user_id"] = int(value)
                except (TypeError, ValueError):
                    pass
            elif key == "location_id":
                try:
                    self.entities["location_id"] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                self.entities[key] = str(value)

    def record_turn(
        self,
        question: str,
        sql: Optional[str],
        answer_summary: Optional[str] = None,
        *,
        error: Optional[str] = None,
        result_columns: Optional[List[str]] = None,
        result_rows: Optional[List[Any]] = None,
    ) -> None:
        """Store compact turn + refresh entities (+ persist to SQLite)."""
        self.extract_entities(question, sql)
        self.ingest_answer_text(answer_summary)
        self.ingest_result_rows(result_columns, result_rows)
        self.last_question = question
        self.last_sql = sql
        summary = answer_summary or error
        if summary:
            self.last_answer_summary = _truncate(summary, MAX_ANSWER_CHARS)

        assistant_bits = []
        if sql:
            assistant_bits.append(f"SQL: {_truncate(sql, MAX_SQL_CHARS)}")
        if summary:
            assistant_bits.append(f"Answer: {_truncate(summary, MAX_ANSWER_CHARS)}")
        if error and not answer_summary:
            assistant_bits.append(f"Error: {_truncate(error, MAX_ANSWER_CHARS)}")
        if not assistant_bits:
            assistant_bits.append("(no SQL)")

        assistant_content = " | ".join(assistant_bits) if assistant_bits else "(no SQL)"

        # In-process prompt history: structured notes only (never role=assistant
        # with "SQL: ... | Answer: ..." — that contaminates JSON output format).
        self.turns.append(
            {
                "question": question,
                "sql": sql,
                "answer": answer_summary,
                "error": error,
            }
        )
        if len(self.turns) > MAX_TURNS:
            self.turns = self.turns[-MAX_TURNS:]

        if self.persist:
            self._save_session()
            memory_store.append_turn(
                self.session_id, "user", question, sql_text=None
            )
            memory_store.append_turn(
                self.session_id,
                "assistant",
                assistant_content,
                sql_text=sql,
                answer_summary=answer_summary,
                error_text=error,
            )

    def format_for_prompt(self) -> str:
        """Compact block injected as a system message (not assistant turns)."""
        lines = [
            f"Session id: {self.session_id}",
            f"Tenant schema: {self.schema_name}",
        ]
        if self.entities:
            ent = ", ".join(f"{k}={v!r}" for k, v in sorted(self.entities.items()))
            lines.append(f"Known entities: {ent}")
        else:
            lines.append("Known entities: (none yet)")

        if self.turns:
            lines.append("Recent turns (context only — your reply must still be JSON):")
            for i, turn in enumerate(self.turns, start=1):
                lines.append(f"  {i}. question: {turn.get('question')}")
                if turn.get("sql"):
                    lines.append(
                        f"     prior_sql: {_truncate(str(turn['sql']), MAX_SQL_CHARS)}"
                    )
                if turn.get("answer"):
                    lines.append(
                        f"     prior_result: {_truncate(str(turn['answer']), MAX_ANSWER_CHARS)}"
                    )
                if turn.get("error"):
                    lines.append(
                        f"     prior_error: {_truncate(str(turn['error']), MAX_ANSWER_CHARS)}"
                    )
        elif self.last_question:
            lines.append(f"Last question: {self.last_question}")
            if self.last_sql:
                lines.append(f"prior_sql: {_truncate(self.last_sql, MAX_SQL_CHARS)}")
            if self.last_answer_summary:
                lines.append(
                    f"prior_result: {_truncate(self.last_answer_summary, MAX_ANSWER_CHARS)}"
                )

        lines.append(
            "Resolve pronouns and vague follow-ups from Known entities / recent turns: "
            "'they/them/their/he/she/his/her/this user/that user/that person' "
            "→ use email and/or user_id already listed. "
            "Do NOT ask for email or user id when Known entities already has them. "
            "Examples: 'what credits do they have?', 'her email', 'same for last month'. "
            "Do not invent entities that are not listed. "
            "Never copy prior_sql/prior_result formatting into your output — "
            "respond with JSON only."
        )
        return "\n".join(lines)

    def messages_for_prompt(self) -> List[Dict[str, str]]:
        """No longer inject prior turns as chat roles (avoids JSON format drift)."""
        return []

    def _save_session(self) -> None:
        memory_store.upsert_session(
            self.session_id,
            self.schema_name,
            self.entities,
            last_question=self.last_question,
            last_sql=self.last_sql,
            last_answer_summary=self.last_answer_summary,
        )


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
