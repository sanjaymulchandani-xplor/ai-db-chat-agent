from __future__ import annotations

import streamlit as st
from openai import OpenAI

from chatbot import (
    PROMPT_STYLE,
    build_schema_context,
    generate_nl_answer,
    generate_sql_response,
    is_safe_select,
    run_query,
)
from database.postgres_connection import get_connection, get_schemas, get_tables
from memory.session import SessionMemory
from secure_store import (
    get_db_path,
    initialize_secrets,
    is_initialized,
    load_secrets,
    reset_all,
    save_secrets,
    unlock,
)

st.set_page_config(page_title="Ask your database questions with AI", page_icon="💬", layout="wide")


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


def _ensure_session_state() -> None:
    defaults = {
        "unlocked": False,
        "fernet": None,
        "openai_api_key": None,
        "connection_string": None,
        "selected_schema": None,
        "schema_tables": None,
        "chat_session": None,
        "messages": [],
        "prompt_style": PROMPT_STYLE or "cot",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_setup() -> None:
    st.title("Ask your database questions with AI")
    st.caption(
        "Bring your own OpenAI key and Postgres connection string. "
        f"Secrets are encrypted in `{get_db_path()}`."
    )
    with st.form("setup_form"):
        passphrase = st.text_input(
            "Master passphrase (min 8 chars)",
            type="password",
            help="Used to encrypt/decrypt secrets. Not stored.",
        )
        passphrase2 = st.text_input("Confirm passphrase", type="password")
        openai_key = st.text_input("OpenAI API key (BYOK)", type="password")
        conn = st.text_input(
            "Postgres connection string",
            placeholder="postgresql://user:pass@localhost:5432/dbname",
            type="password",
        )
        submitted = st.form_submit_button("Save encrypted secrets", type="primary")
        if submitted:
            if passphrase != passphrase2:
                st.error("Passphrases do not match.")
                return
            try:
                initialize_secrets(passphrase, openai_key, conn)
                fernet = unlock(passphrase)
                secrets = load_secrets(fernet)
                st.session_state.unlocked = True
                st.session_state.fernet = fernet
                st.session_state.openai_api_key = secrets["openai_api_key"]
                st.session_state.connection_string = secrets["connection_string"]
                st.success("Secrets saved. Loading chat…")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_unlock() -> None:
    st.title("Ask your database questions with AI")
    st.caption(f"Encrypted secrets found at `{get_db_path()}`.")
    with st.form("unlock_form"):
        passphrase = st.text_input("Master passphrase", type="password")
        submitted = st.form_submit_button("Unlock", type="primary")
        if submitted:
            try:
                fernet = unlock(passphrase)
                secrets = load_secrets(fernet)
                st.session_state.unlocked = True
                st.session_state.fernet = fernet
                st.session_state.openai_api_key = secrets["openai_api_key"]
                st.session_state.connection_string = secrets["connection_string"]
                st.success("Unlocked.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    if st.button("Reset all secrets (destructive)"):
        reset_all()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.warning("Secrets wiped. Reload to set up again.")
        st.rerun()


def _render_settings() -> None:
    st.subheader("Settings")
    st.write(f"OpenAI key: `{_mask(st.session_state.openai_api_key or '')}`")
    st.write(f"Connection: `{_mask(st.session_state.connection_string or '', keep=12)}`")

    with st.form("update_secrets"):
        st.markdown("Update secrets (leave blank to keep current)")
        new_key = st.text_input("New OpenAI API key", type="password")
        new_conn = st.text_input("New connection string", type="password")
        if st.form_submit_button("Update encrypted secrets"):
            try:
                save_secrets(
                    st.session_state.fernet,
                    openai_api_key=new_key or None,
                    connection_string=new_conn or None,
                )
                secrets = load_secrets(st.session_state.fernet)
                st.session_state.openai_api_key = secrets["openai_api_key"]
                st.session_state.connection_string = secrets["connection_string"]
                st.success("Updated.")
            except Exception as exc:
                st.error(str(exc))

    st.session_state.prompt_style = st.selectbox(
        "Prompt style",
        options=["cot", "oneshot"],
        index=0 if st.session_state.prompt_style != "oneshot" else 1,
    )

    if st.button("Lock / log out"):
        st.session_state.unlocked = False
        st.session_state.fernet = None
        st.session_state.openai_api_key = None
        st.session_state.connection_string = None
        st.session_state.selected_schema = None
        st.session_state.schema_tables = None
        st.session_state.chat_session = None
        st.session_state.messages = []
        st.rerun()


def _load_schemas() -> list[str]:
    conn = get_connection(st.session_state.connection_string)
    try:
        cur = conn.cursor()
        return get_schemas(cur)
    finally:
        conn.close()


def _ensure_chat_ready(schema_name: str) -> None:
    if (
        st.session_state.chat_session is None
        or st.session_state.chat_session.schema_name != schema_name
    ):
        st.session_state.chat_session = SessionMemory(schema_name=schema_name)
        st.session_state.messages = []

    if st.session_state.selected_schema != schema_name or not st.session_state.schema_tables:
        conn = get_connection(st.session_state.connection_string)
        try:
            cur = conn.cursor()
            st.session_state.schema_tables = get_tables(cur, schema_name)
            st.session_state.selected_schema = schema_name
        finally:
            conn.close()


def _format_usage(label: str, usage: dict | None) -> str | None:
    if not usage:
        return None
    return (
        f"[{label} tokens] input: {usage.get('prompt_tokens')} | "
        f"output: {usage.get('completion_tokens')} | "
        f"total: {usage.get('total_tokens')}"
    )


def _handle_question(question: str) -> None:
    schema = st.session_state.selected_schema
    session: SessionMemory = st.session_state.chat_session
    oai = OpenAI(api_key=st.session_state.openai_api_key)

    st.session_state.messages.append({"role": "user", "content": question})

    conn = get_connection(st.session_state.connection_string)
    try:
        cur = conn.cursor()
        schema_context, _ = build_schema_context(
            cur, schema, st.session_state.schema_tables, question=question
        )
        try:
            sql_result = generate_sql_response(
                question,
                schema,
                schema_context,
                prompt_style=st.session_state.prompt_style,
                session=session,
                openai_client=oai,
                quiet=True,
            )
            sql = sql_result.get("sql")
            sql_usage = sql_result.get("usage")
            if sql is None:
                err = sql_result.get("error") or "I need more detail to write a safe query."
                raise ValueError(err)
        except Exception as exc:
            session.record_turn(question, sql=None, error=str(exc))
            st.session_state.messages.append(
                {"role": "assistant", "content": f"Could not generate SQL: {exc}"}
            )
            return

        if not is_safe_select(sql, schema):
            session.record_turn(question, sql, error="blocked by safety check")
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "That query failed the safety check (read-only SELECT only).",
                    "sql": sql,
                    "token_lines": [
                        line
                        for line in [_format_usage("SQL gen", sql_usage)]
                        if line
                    ],
                }
            )
            return

        try:
            columns, rows = run_query(cur, sql)
            answer, answer_usage = generate_nl_answer(
                question, columns, rows, openai_client=oai
            )
            session.record_turn(
                question,
                sql,
                answer_summary=answer,
                result_columns=list(columns),
                result_rows=rows,
            )
            token_lines = [
                line
                for line in (
                    _format_usage("SQL gen", sql_usage),
                    _format_usage("Answer gen", answer_usage),
                )
                if line
            ]
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sql": sql,
                    "row_count": len(rows),
                    "token_lines": token_lines,
                }
            )
        except Exception as exc:
            session.record_turn(question, sql, error=str(exc))
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"SQL ran into an error: {exc}",
                    "sql": sql,
                    "token_lines": [
                        line
                        for line in [_format_usage("SQL gen", sql_usage)]
                        if line
                    ],
                }
            )
    finally:
        conn.close()


def _render_chat() -> None:
    st.title("Ask your database questions with AI")

    with st.sidebar:
        st.header("Workspace")
        try:
            schemas = _load_schemas()
        except Exception as exc:
            st.error(f"Could not connect to Postgres: {exc}")
            _render_settings()
            return

        schema = st.selectbox(
            "Tenant schema",
            options=schemas,
            index=schemas.index(st.session_state.selected_schema)
            if st.session_state.selected_schema in schemas
            else 0,
        )
        _ensure_chat_ready(schema)

        st.caption(f"Session: `{st.session_state.chat_session.session_id}`")
        c1, c2 = st.columns(2)
        if c1.button("Clear memory"):
            st.session_state.chat_session.clear()
            st.session_state.messages = []
            st.rerun()
        if c2.button("Reset session"):
            st.session_state.chat_session.reset()
            st.session_state.messages = []
            st.rerun()

        with st.expander("Session memory"):
            st.code(st.session_state.chat_session.format_for_prompt())

        st.divider()
        _render_settings()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"):
                with st.expander("Generated SQL"):
                    st.code(msg["sql"], language="sql")
            meta_bits = []
            if msg.get("row_count") is not None:
                meta_bits.append(f"Rows returned: {msg['row_count']}")
            for line in msg.get("token_lines") or []:
                meta_bits.append(line)
            if meta_bits:
                st.caption("  \n".join(meta_bits))

    question = st.chat_input("Ask a question about this tenant…")
    if question:
        with st.spinner("Thinking…"):
            _handle_question(question)
        st.rerun()


def main() -> None:
    _ensure_session_state()

    if not is_initialized():
        _render_setup()
        return

    if not st.session_state.unlocked:
        _render_unlock()
        return

    _render_chat()


if __name__ == "__main__":
    main()
