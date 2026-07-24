from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Allow `python -m evals.run_evals` from chat-tool/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot import generate_sql_response, is_safe_select  # noqa: E402
from evals.fixture_schema import SCHEMA_NAME, build_fixture_schema_context  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "cases.json"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in _norm(haystack)


def _has_name_label(sql: str) -> bool:
    n = _norm(sql)
    if ".name" in n or "full_name" in n:
        return True
    if re.search(r"\bas\s+\w*name\w*", n):
        return True
    return False


def eval_safety_case(case: dict[str, Any]) -> tuple[bool, str]:
    sql = case["sql"]
    schema = case.get("schema_name", SCHEMA_NAME)
    expect = bool(case["expect_safe"])
    got = is_safe_select(sql, schema)
    if got == expect:
        return True, f"safe={got} (expected {expect})"
    return False, f"safe={got} but expected {expect}"


def eval_sql_gen_case(
    case: dict[str, Any],
    schema_context: str,
    schema_name: str,
    prompt_style: str,
) -> tuple[bool, str, dict[str, Any]]:
    question = case["question"]
    result = generate_sql_response(
        question,
        schema_name,
        schema_context,
        prompt_style=prompt_style,
        quiet=True,
    )
    sql = result.get("sql")
    error = result.get("error")
    failures: list[str] = []

    expect_null = bool(case.get("expect_sql_null"))
    alt_unsafe = bool(case.get("alt_accept_unsafe_sql"))

    if expect_null:
        if sql is None:
            return True, f"sql=null ok ({error or 'no error msg'})", result
        if alt_unsafe and not is_safe_select(sql, schema_name):
            return True, "sql present but unsafe (accepted as refusal path)", result
        failures.append(f"expected sql=null, got SQL: {sql[:200]}")
        return False, "; ".join(failures), result

    if sql is None:
        failures.append(f"expected SQL, got null ({error})")
        return False, "; ".join(failures), result

    for needle in case.get("must_contain") or []:
        if not _contains(sql, needle):
            failures.append(f"missing required: {needle!r}")

    for group in case.get("must_contain_any") or []:
        if not any(_contains(sql, n) for n in group):
            failures.append(f"missing any of: {group!r}")

    for needle in case.get("must_not_contain") or []:
        if _contains(sql, needle):
            failures.append(f"forbidden present: {needle!r}")

    if case.get("require_name_label") and not _has_name_label(sql):
        failures.append("expected a readable name label (.name or AS *name*)")

    if case.get("require_safe", True) and not is_safe_select(sql, schema_name):
        failures.append("failed is_safe_select")

    if failures:
        return False, "; ".join(failures), result
    return True, "ok", result


def load_cases() -> dict[str, Any]:
    with CASES_PATH.open() as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mariana Text-to-SQL evals")
    parser.add_argument(
        "--style",
        default=os.environ.get("PROMPT_STYLE", "cot"),
        choices=("cot", "oneshot"),
        help="Prompt style for sql_gen cases",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this case id (repeatable)",
    )
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="Skip LLM sql_gen cases (no OpenAI key needed)",
    )
    parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Print generated SQL for each sql_gen case",
    )
    args = parser.parse_args()

    suite = load_cases()
    schema_name = suite.get("schema_name", SCHEMA_NAME)
    cases = suite["cases"]
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            print(f"Unknown case ids: {sorted(missing)}")
            return 2

    schema_context = build_fixture_schema_context(schema_name)
    passed = 0
    failed = 0
    skipped = 0

    print(f"Running {len(cases)} cases (style={args.style})\n")

    for case in cases:
        case_id = case["id"]
        case_type = case.get("type", "sql_gen")

        if args.safety_only and case_type != "safety":
            skipped += 1
            print(f"SKIP  {case_id} (safety-only)")
            continue

        if case_type == "safety":
            ok, detail = eval_safety_case(case)
            result = {}
        elif case_type == "sql_gen":
            if not os.environ.get("OPENAI_API_KEY"):
                print(f"FAIL  {case_id} — OPENAI_API_KEY not set")
                failed += 1
                continue
            ok, detail, result = eval_sql_gen_case(
                case, schema_context, schema_name, args.style
            )
        else:
            print(f"FAIL  {case_id} — unknown type {case_type}")
            failed += 1
            continue

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"{status}  {case_id} — {detail}")
        if args.show_sql and result.get("sql"):
            print(f"      SQL: {result['sql']}")
        if not ok and result.get("sql") is None and result.get("error"):
            print(f"      error: {result['error']}")
        if not ok and result.get("sql"):
            print(f"      SQL: {result['sql']}")

    total = passed + failed
    print()
    print(f"Score: {passed}/{total} passed ({failed} failed, {skipped} skipped)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
