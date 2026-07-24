# DB chat tool (works for Mariana-Django DB with multi tenant support) 

Ask natural-language questions about a Mariana tenant Postgres schema. The tool:

1. Generates a read-only SQL query (default: chain-of-thought prompt)
2. Safety-checks the SQL
3. Runs it
4. Streams a plain-English answer

## Setup

```bash
cd chat-tool
uv sync   # installs streamlit, cryptography, openai, etc.
```

### Streamlit UI (recommended) — BYOK

```bash
streamlit run ui_app.py
```

On first launch, enter:

1. Master passphrase (encrypts secrets; never stored)
2. OpenAI API key (BYOK)
3. Postgres connection string

Secrets are stored encrypted in `database/app_secrets.db`. Later launches only need the passphrase to unlock.

### CLI (optional)

```bash
# .env with OPENAI_API_KEY + CONNECTION_STRING still works for CLI
python -m database.save_schema
python chatbot.py
```

## Prompt styles

| Env var | Values | Meaning |
|---|---|---|
| `PROMPT_STYLE` | `cot` (default) | Chain-of-thought JSON: `reasoning` + `sql` |
| `PROMPT_STYLE` | `oneshot` | Shorter few-shot prompt; JSON `sql` only |
| `DEBUG_SCHEMA` | `1` / `true` | Print model reasoning + table list |

```bash
PROMPT_STYLE=cot python chatbot.py
PROMPT_STYLE=oneshot python chatbot.py
DEBUG_SCHEMA=1 PROMPT_STYLE=cot python chatbot.py
```

Domain glossary, join tips, status enums, and few-shot SQL examples live under `prompts/`.
Live column lists are filtered to a core business allowlist (plus reporting `view_*` when the question looks analytics-shaped).

## Session memory (Vector DB must be add eventually.)

In-process for follow-ups — keyed by `session_id` (UUID), no auth.
Turns are also saved to SQLite at `database/session_memory.db`.

| Command | Effect |
|---|---|
| `memory` / `session` | Print current session memory |
| `clear` | Wipe entities + turns (same session id) |
| `reset` | New session id + empty memory |
| `exit` / `quit` | Leave chat |

Follow-ups like “same for last month” use extracted entities (email, user_id, location_id) plus the last few Q→SQL→answer turns. Memory is injected into **SQL generation only**, not the NL answer step.

### Read persisted memories

```bash
python read_memory.py                 # list all sessions
python read_memory.py --latest        # most recent session + turns
python read_memory.py <session_id>    # one session in detail
```

## Evals

Structural + safety checks for prompt regressions (cases under `evals/cases.json`):

```bash
# Free: safety-only (no OpenAI)
python -m evals.run_evals --safety-only

# Full suite (needs OPENAI_API_KEY)
python -m evals.run_evals
python -m evals.run_evals --style oneshot
python -m evals.run_evals --case popular_membership --show-sql
```

Exit code `0` = all run cases passed; `1` = failures.
