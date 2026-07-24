import os
import re
import json
import asyncio
import aiosqlite
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # reads .env from the current working directory by default

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(SCRIPT_DIR, "database", "schema_store.db")
from database.postgres_connection import get_connection, get_schemas, prompt_for_schema
from memory.session import SessionMemory
from prompts.domain_glossary import (
    CORE_TABLES,
    REPORTING_VIEWS,
    filter_tables_for_question,
)
from prompts.sql_system_prompt import build_cot_sql_prompt, build_oneshot_sql_prompt

MODEL = "gpt-4o-mini"
# PROMPT_STYLE: "cot" (default, chain-of-thought) or "oneshot"
PROMPT_STYLE = os.environ.get("PROMPT_STYLE", "cot").strip().lower()
DEBUG_SCHEMA = os.environ.get("DEBUG_SCHEMA", "").strip().lower() in ("1", "true", "yes")
api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=api_key) if api_key else None


def get_openai_client(openai_api_key: str | None = None) -> OpenAI:
    if openai_api_key:
        return OpenAI(api_key=openai_api_key)
    if client is not None:
        return client
    raise ValueError("OpenAI API key is required (BYOK or OPENAI_API_KEY env).")

FORBIDDEN_SQL_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "merge",
    "upsert",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "copy",
    "call",
    "execute",
    "do",
    "into",  # SELECT INTO / INSERT INTO
    "pg_sleep",
    "dblink",
    "lo_import",
    "set role",
    "set session",
)

# Word-boundary match; "into" still caught for SELECT INTO / INSERT INTO.
_FORBIDDEN_RE = re.compile(
    r"\b("
    + "|".join(re.escape(k) for k in FORBIDDEN_SQL_KEYWORDS if " " not in k)
    + r")\b"
    + r"|\bset\s+role\b|\bset\s+session\b",
    re.IGNORECASE,
)


async def get_tables_for_schema(schema_name):
    async with aiosqlite.connect(SQLITE_DB) as db:
        async with db.execute("""
            SELECT table_name FROM schema_tables
            WHERE schema_name = ?
            ORDER BY table_name;
        """, (schema_name,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


def get_columns_for_table(pg_cursor, schema_name, table_name):
    pg_cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
    """, (schema_name, table_name))
    return pg_cursor.fetchall()


def build_schema_context(pg_cursor, schema_name, tables, question=None):
    """Live column dump for allowlisted tables only (optionally + reporting views)."""
    selected = filter_tables_for_question(tables, question)
    lines = []
    for table in selected:
        columns = get_columns_for_table(pg_cursor, schema_name, table)
        if not columns:
            continue
        col_str = ", ".join(f"{col} ({dtype})" for col, dtype in columns)
        lines.append(f"- {schema_name}.{table}: {col_str}")
    return "\n".join(lines), selected



def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    text = text.replace("```json", "").replace("```SQL", "").replace("```sql", "")
    text = text.replace("```", "").strip()
    return text


def _extract_sql_from_text(raw: str) -> str | None:
    """Best-effort recovery when the model returns non-JSON (e.g. 'SQL: SELECT ...')."""
    text = _strip_code_fences(raw)

    def _clean(sql: str) -> str | None:
        sql = re.split(r"\s*\|\s*Answer\b", sql, maxsplit=1, flags=re.I)[0]
        sql = sql.strip().rstrip(";").strip()
        if re.match(r"(?is)^(SELECT|WITH)\b", sql):
            return sql
        return None

    # Prefer explicit SQL: prefix
    labeled = re.search(r"(?is)\bSQL\s*:\s*((?:SELECT|WITH)\b.+)", text)
    if labeled:
        cleaned = _clean(labeled.group(1))
        if cleaned:
            return cleaned

    # Bare SELECT / WITH
    bare = re.search(r"(?is)\b((?:WITH|SELECT)\b.+)", text)
    if bare:
        return _clean(bare.group(1))
    return None


def parse_model_sql_payload(raw: str) -> dict:
    """Parse model output into {sql, error, reasoning}. Recovers from format drift."""
    text = _strip_code_fences(raw)

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object substring
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None

    if isinstance(parsed, dict):
        sql = parsed.get("sql")
        error = parsed.get("error")
        reasoning = parsed.get("reasoning")
        if isinstance(sql, str):
            sql = sql.strip() or None
        return {"sql": sql, "error": error, "reasoning": reasoning}

    recovered = _extract_sql_from_text(text)
    if recovered:
        return {
            "sql": recovered,
            "error": None,
            "reasoning": "recovered_from_non_json",
        }

    raise ValueError(f"Could not parse SQL from model response: {raw}")


def generate_sql_response(
    user_question,
    schema_name,
    schema_context,
    prompt_style=None,
    *,
    quiet=False,
    session: SessionMemory | None = None,
    openai_client: OpenAI | None = None,
    openai_api_key: str | None = None,
):
    """Call the model and return parsed JSON fields (sql may be null)."""
    oai = openai_client or get_openai_client(openai_api_key)
    style = (prompt_style or PROMPT_STYLE).strip().lower()
    if style == "oneshot":
        system_prompt = build_oneshot_sql_prompt(schema_name, schema_context)
    else:
        system_prompt = build_cot_sql_prompt(schema_name, schema_context)

    messages = [{"role": "system", "content": system_prompt}]
    if session is not None:
        messages.append(
            {
                "role": "system",
                "content": "Session memory (follow-ups):\n"
                + session.format_for_prompt(),
            }
        )
        # Intentionally do NOT append prior turns as assistant messages.
    messages.append({"role": "user", "content": user_question})

    def _call(msgs):
        kwargs = {
            "model": MODEL,
            "messages": msgs,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return oai.chat.completions.create(**kwargs)

    response = _call(messages)
    usage = response.usage
    if not quiet:
        print(
            f"[SQL gen tokens] input: {usage.prompt_tokens} | "
            f"output: {usage.completion_tokens} | total: {usage.total_tokens} "
            f"(style={style})"
        )

    raw = (response.choices[0].message.content or "").strip()

    try:
        parsed = parse_model_sql_payload(raw)
    except ValueError:
        # One silent retry with a hard format reminder
        if not quiet:
            print("[SQL gen] parse failed — retrying once with JSON-only reminder")
        retry_messages = list(messages) + [
            {
                "role": "user",
                "content": (
                    "Your previous reply was not valid JSON. "
                    'Respond with ONLY a JSON object like '
                    '{"reasoning":"...","sql":"SELECT ...","error":null}. '
                    "No markdown. No 'SQL:' or 'Answer:' prefixes."
                ),
            }
        ]
        response = _call(retry_messages)
        usage2 = response.usage
        if not quiet and usage2:
            print(
                f"[SQL gen retry tokens] input: {usage2.prompt_tokens} | "
                f"output: {usage2.completion_tokens} | total: {usage2.total_tokens}"
            )
        if usage2:
            usage = usage2
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_model_sql_payload(raw)

    sql = parsed.get("sql")
    error = parsed.get("error")
    reasoning = parsed.get("reasoning")

    if reasoning and DEBUG_SCHEMA and not quiet:
        print(f"[Reasoning]: {reasoning}")

    return {
        "sql": sql,
        "error": error,
        "reasoning": reasoning,
        "raw": raw,
        "prompt_style": style,
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
        },
    }


def generate_sql(
    user_question,
    schema_name,
    schema_context,
    prompt_style=None,
    session: SessionMemory | None = None,
    *,
    openai_client: OpenAI | None = None,
    openai_api_key: str | None = None,
):
    result = generate_sql_response(
        user_question,
        schema_name,
        schema_context,
        prompt_style=prompt_style,
        session=session,
        openai_client=openai_client,
        openai_api_key=openai_api_key,
    )
    sql = result.get("sql")
    error = result.get("error")

    if sql is None:
        raise ValueError(error or "I need more detail to write a safe query.")

    if not isinstance(sql, str) or not sql.strip():
        raise ValueError(error or "Model returned an empty SQL query.")

    return sql.strip()



def _strip_sql_string_literals(sql: str) -> str:
    """Remove single-quoted string literals so keyword/schema checks ignore values."""
    return re.sub(r"'(?:''|[^'])*'", "''", sql)


def is_safe_select(sql, schema_name):
    """Allow a single SELECT / WITH…SELECT against the selected tenant schema only."""
    normalized = sql.strip()
    if not normalized:
        return False

    # Multi-statement / comment injection
    if ";" in normalized.rstrip(";"):
        return False
    if "--" in normalized or "/*" in normalized:
        return False

    lowered = normalized.lower().lstrip()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    scrubbed = _strip_sql_string_literals(normalized)
    if _FORBIDDEN_RE.search(scrubbed):
        return False

    # Only treat ident.ident as schema.table when the right side looks like a
    # known table/view (not alias.column like u.email).
    known_tables = {t.lower() for t in (CORE_TABLES | REPORTING_VIEWS)}
    for left, right in re.findall(
        r"(?i)\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b",
        scrubbed,
    ):
        right_l = right.lower()
        if right_l in known_tables or right_l.startswith("view_"):
            if left.lower() != schema_name.lower():
                return False

    return True


def run_query(pg_cursor, sql):
    pg_cursor.execute(sql)
    columns = [desc[0] for desc in pg_cursor.description]
    rows = pg_cursor.fetchall()
    return columns, rows


NL_ANSWER_SYSTEM = (
    "You answer questions in plain natural language based only on the SQL "
    "query results provided. Be concise and direct. Prefer human-readable "
    "fields (names, emails, class names, locations, datetimes, statuses). "
    "Do not highlight internal ids (user_id, reservation_id, class_session_id, "
    "type ids) unless the user asked for an id or no name columns are present. "
    "Do not invent numbers or rows that are not in the results. If the preview "
    "is truncated, say so and use Total rows for scale."
)


def generate_nl_answer(
    user_question,
    columns,
    rows,
    *,
    openai_client: OpenAI | None = None,
    openai_api_key: str | None = None,
) -> tuple[str, dict | None]:
    """Non-streaming NL answer. Returns (answer_text, usage_dict)."""
    oai = openai_client or get_openai_client(openai_api_key)
    preview_limit = 20
    result_preview = rows[:preview_limit]
    truncated = len(rows) > preview_limit
    context = (
        f"Columns: {columns}\n"
        f"Rows (preview up to {preview_limit}): {result_preview}\n"
        f"Total rows: {len(rows)}\n"
        f"Preview truncated: {truncated}"
    )
    response = oai.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": NL_ANSWER_SYSTEM},
            {"role": "user", "content": f"Question: {user_question}\n\n{context}"},
        ],
        temperature=0.3,
    )
    answer = (response.choices[0].message.content or "").strip()
    usage = response.usage
    usage_dict = None
    if usage:
        usage_dict = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
    return answer, usage_dict


def generate_nl_answer_streamed(
    user_question,
    columns,
    rows,
    *,
    openai_client: OpenAI | None = None,
    openai_api_key: str | None = None,
):
    oai = openai_client or get_openai_client(openai_api_key)
    preview_limit = 20
    result_preview = rows[:preview_limit]
    truncated = len(rows) > preview_limit
    context = (
        f"Columns: {columns}\n"
        f"Rows (preview up to {preview_limit}): {result_preview}\n"
        f"Total rows: {len(rows)}\n"
        f"Preview truncated: {truncated}"
    )

    stream = oai.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": NL_ANSWER_SYSTEM},
            {"role": "user", "content": f"Question: {user_question}\n\n{context}"},
        ],
        temperature=0.3,
        stream=True,
        stream_options={"include_usage": True},  # required to get usage in a streamed response
    )

    print("Bot: ", end="", flush=True)

    full_answer = ""
    usage = None

    for chunk in stream:
        # Usage arrives in the final chunk, where choices is empty
        if chunk.usage is not None:
            usage = chunk.usage

        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                print(delta, end="", flush=True)
                full_answer += delta

    print()  # newline after streaming finishes

    if usage:
        print(
            f"[Answer gen tokens] input: {usage.prompt_tokens} | "
            f"output: {usage.completion_tokens} | total: {usage.total_tokens}"
        )

    return full_answer



async def main():
    pg_connection = get_connection()
    pg_cursor = pg_connection.cursor()

    schemas = get_schemas(pg_cursor)
    selected_schema = prompt_for_schema(schemas)

    if not selected_schema:
        pg_cursor.close()
        pg_connection.close()
        return

    tables = await get_tables_for_schema(selected_schema)
    if not tables:
        print(f"No cached tables found for '{selected_schema}'. Run save_schema.py first.")
        pg_cursor.close()
        pg_connection.close()
        return

    print(f"\nBuilding core schema context for '{selected_schema}'...")
    # Baseline context: core tables + common reporting views (question=None).
    schema_context, selected_tables = build_schema_context(
        pg_cursor, selected_schema, tables, question=None
    )
    print(
        f"Using {len(selected_tables)} allowlisted tables/views "
        f"(PROMPT_STYLE={PROMPT_STYLE})."
    )
    if DEBUG_SCHEMA:
        print("[DEBUG] Tables:", ", ".join(selected_tables))
        print("[DEBUG] Schema context chars:", len(schema_context))

    print(f"\nReady. Ask questions about '{selected_schema}' (type 'exit' to quit).\n")
    print("Tip: set PROMPT_STYLE=oneshot for the shorter prompt; DEBUG_SCHEMA=1 for reasoning.")
    print("Commands: clear (wipe memory) | reset (new session id) | memory (show session)\n")

    session = SessionMemory(schema_name=selected_schema)
    print(f"Session: {session.session_id}\n")

    while True:
        user_question = input("You: ").strip()
        if user_question.lower() in ("exit", "quit"):
            break
        if not user_question:
            continue

        cmd = user_question.lower()
        if cmd in ("clear", "clear memory"):
            session.clear()
            print("Bot: Session memory cleared (same session id).\n")
            continue
        if cmd == "reset":
            session.reset()
            print(f"Bot: New session started: {session.session_id}\n")
            continue
        if cmd in ("memory", "session"):
            print(session.format_for_prompt())
            print()
            continue

        try:
            # Rebuild context when the question looks analytics-shaped so extra
            # view_* columns are available without always paying that cost.
            turn_context, turn_tables = build_schema_context(
                pg_cursor, selected_schema, tables, question=user_question
            )
            if DEBUG_SCHEMA and turn_tables != selected_tables:
                print(f"[DEBUG] Turn tables ({len(turn_tables)}): {', '.join(turn_tables)}")

            sql = generate_sql(
                user_question, selected_schema, turn_context, session=session
            )
            print(f"[Generated SQL]: {sql}")

            if not is_safe_select(sql, selected_schema):
                print(
                    "Bot: I can only run safe SELECT queries against this tenant "
                    "schema, and this one didn't pass that check."
                )
                session.record_turn(
                    user_question, sql, error="blocked by safety check"
                )
                continue

            columns, rows = run_query(pg_cursor, sql)
            answer = generate_nl_answer_streamed(user_question, columns, rows)
            session.record_turn(
                user_question,
                sql,
                answer_summary=answer,
                result_columns=list(columns),
                result_rows=rows,
            )
            print()

        except Exception as e:
            session.record_turn(user_question, sql=None, error=str(e))
            print(f"Bot: Something went wrong — {e}\n")

    pg_cursor.close()
    pg_connection.close()


if __name__ == "__main__":
    asyncio.run(main())
