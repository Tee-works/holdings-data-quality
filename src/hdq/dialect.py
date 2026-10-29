"""Render control and staging SQL for a target engine.

Controls are written once, in SQL that DuckDB and Snowflake both accept, with two Jinja
macros (sql/macros/dialect.sql) for the regular-expression functions the engines name
differently. DuckDB runs the public dashboard; Snowflake runs the same files unchanged.
"""

from __future__ import annotations

from functools import cache

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from hdq.config import SQL_DIR

DIALECTS = ("duckdb", "snowflake")


@cache
def _env() -> Environment:
    return Environment(loader=FileSystemLoader(SQL_DIR / "macros"), undefined=StrictUndefined)


def render(sql: str, dialect: str = "duckdb") -> str:
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}; expected one of {DIALECTS}")
    env = _env()
    macros = env.get_template("dialect.sql").make_module({"dialect": dialect})
    return env.from_string(sql).render(
        dialect=dialect, **{name: getattr(macros, name) for name in ("full_match", "replace_all")}
    )
