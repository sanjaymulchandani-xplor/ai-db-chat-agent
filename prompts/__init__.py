"""Mariana domain prompts for NL → SQL generation."""

from prompts.domain_glossary import (
    CORE_TABLES,
    EXCLUDE_PREFIXES,
    REPORTING_VIEWS,
    REPORTING_QUESTION_HINTS,
    build_domain_glossary_text,
    filter_tables_for_question,
)
from prompts.sql_examples import build_sql_examples_text
from prompts.sql_system_prompt import (
    build_cot_sql_prompt,
    build_oneshot_sql_prompt,
)

__all__ = [
    "CORE_TABLES",
    "EXCLUDE_PREFIXES",
    "REPORTING_VIEWS",
    "REPORTING_QUESTION_HINTS",
    "build_domain_glossary_text",
    "filter_tables_for_question",
    "build_sql_examples_text",
    "build_cot_sql_prompt",
    "build_oneshot_sql_prompt",
]
