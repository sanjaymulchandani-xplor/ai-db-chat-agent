from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python read_memory.py` from chat-tool/
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.store import get_db_path, get_session, get_turns, list_sessions


def print_session_list() -> int:
    sessions = list_sessions()
    db = get_db_path()
    if not sessions:
        print(f"No sessions found in {db}")
        return 0

    print(f"Memory DB: {db}\n")
    print(f"{'#':<4} {'schema':<16} {'turns':<6} {'updated_at':<28} session_id")
    print("-" * 100)
    for i, s in enumerate(sessions, start=1):
        print(
            f"{i:<4} {s['schema_name']:<16} {s['turn_count']:<6} "
            f"{s['updated_at']:<28} {s['session_id']}"
        )
        if s.get("last_question"):
            q = " ".join(str(s["last_question"]).split())
            if len(q) > 80:
                q = q[:77] + "..."
            print(f"     last: {q}")
    print()
    print("Detail: python read_memory.py <session_id>")
    print("Latest: python read_memory.py --latest")
    return 0


def print_session_detail(session_id: str) -> int:
    session = get_session(session_id)
    if not session:
        print(f"Session not found: {session_id}")
        return 1

    entities = json.loads(session.get("entities_json") or "{}")
    turns = get_turns(session_id)

    print(f"Memory DB: {get_db_path()}")
    print(f"Session:   {session['session_id']}")
    print(f"Schema:    {session['schema_name']}")
    print(f"Created:   {session['created_at']}")
    print(f"Updated:   {session['updated_at']}")
    print(f"Entities:  {entities or '(none)'}")
    if session.get("last_question"):
        print(f"Last Q:    {session['last_question']}")
    if session.get("last_sql"):
        print(f"Last SQL:  {session['last_sql']}")
    if session.get("last_answer_summary"):
        print(f"Last ans:  {session['last_answer_summary']}")
    print()
    print(f"Turns ({len(turns)}):")
    print("-" * 60)
    if not turns:
        print("(no turns recorded)")
        return 0

    for t in turns:
        print(f"[{t['created_at']}] {t['role'].upper()}")
        print(f"  {t['content']}")
        if t.get("sql_text"):
            print(f"  SQL: {t['sql_text']}")
        if t.get("error_text"):
            print(f"  ERROR: {t['error_text']}")
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read chat session memories")
    parser.add_argument(
        "session_id",
        nargs="?",
        help="Session UUID to inspect",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Show the most recently updated session",
    )
    args = parser.parse_args()

    if args.latest:
        sessions = list_sessions()
        if not sessions:
            print(f"No sessions found in {get_db_path()}")
            return 0
        return print_session_detail(sessions[0]["session_id"])

    if args.session_id:
        return print_session_detail(args.session_id)

    return print_session_list()


if __name__ == "__main__":
    raise SystemExit(main())
