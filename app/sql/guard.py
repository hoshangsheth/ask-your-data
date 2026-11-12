"""
Static validation of model-generated SQL (first of three safety layers; see app/db/executor.py).

Rules enforced, by parsing the SQL with sqlglot (no regexes):
    - exactly one statement, and it must be a read-only query (SELECT / WITH / UNION ...)
    - only allow-listed tables; no schema-qualified names (blocks system catalogs)
    - no write/DDL/session nodes anywhere in the tree, no row locks (FOR UPDATE), no SELECT INTO
    - no dangerous functions (pg_sleep, file readers, dblink, load_extension, ...)
    - a LIMIT no larger than max_rows (added or clamped)

Usage:
    from app.sql.guard import validate_sql, SQLValidationError
    v = validate_sql(sql, dialect="postgres", allowed_tables=ALLOWED_TABLES, max_rows=500)
    v.sql            # normalised, pretty-printed SQL that is safe to run
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Expression types that must never appear. getattr() keeps this working across sqlglot versions.
_FORBIDDEN_NAMES = [
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Drop",
    "Create",
    "Alter",
    "TruncateTable",
    "Command",
    "Pragma",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    "Grant",
    "Copy",
    "Into",
    "Lock",
    "Use",
    "Attach",
    "Detach",
    "LoadData",
    "Analyze",
]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NAMES if hasattr(exp, n))

# Functions that can sleep, read files, open connections or change server state.
DENIED_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "lo_import",
        "lo_export",
        "lo_get",
        "dblink",
        "dblink_exec",
        "set_config",
        "query_to_xml",
        "copy",
        "load_extension",
        "readfile",
        "writefile",
        "edit",
        "fts3_tokenizer",
        "sleep",
        "benchmark",
    }
)


class SQLValidationError(ValueError):
    """The SQL is unsafe or invalid. The message is fed back to the model so it can fix it."""


@dataclass
class ValidatedSQL:
    sql: str  # normalised SQL to execute
    tables: list[str]  # real tables read (CTE names excluded)
    limit_applied: bool  # True if a LIMIT was added or reduced


def _function_name(node: exp.Func) -> str:
    """Lower-case function name for both known (typed) and unknown (Anonymous) functions."""
    return str(node.name).lower() if isinstance(node, exp.Anonymous) else node.sql_name().lower()


def _parse_single_query(sql: str, dialect: str) -> exp.Query:
    """Parse and require exactly one read-only query statement."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError as e:
        raise SQLValidationError(f"could not parse SQL: {str(e).splitlines()[0][:300]}") from e
    if len(statements) != 1:
        raise SQLValidationError("exactly one SQL statement is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SQLValidationError(f"only read-only SELECT queries are allowed, got {tree.key.upper()}")
    return tree


def _check_nodes(tree: exp.Query) -> None:
    """Reject forbidden statement types and dangerous functions anywhere in the tree."""
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(f"{node.key.upper()} is not allowed; write a single SELECT query")
        if isinstance(node, exp.Func) and _function_name(node) in DENIED_FUNCTIONS:
            raise SQLValidationError(f"function {_function_name(node)}() is not allowed")


def _check_tables(tree: exp.Query, dialect: str, allowed_tables: frozenset[str] | set[str]) -> list[str]:
    """Every table must be allow-listed (or a CTE defined in the same query)."""
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if not name:
            raise SQLValidationError("table functions are not allowed")
        if t.db or t.catalog:
            raise SQLValidationError(f"schema-qualified table '{t.sql(dialect=dialect)}' is not allowed")
        if name in cte_names:
            continue
        if name not in allowed_tables:
            raise SQLValidationError(f"unknown table '{t.name}'. Allowed tables: {', '.join(sorted(allowed_tables))}")
        tables.append(name)
    if not tables:
        raise SQLValidationError("query must read from at least one of the allowed tables")
    return sorted(set(tables))


def _enforce_limit(tree: exp.Query, max_rows: int) -> tuple[exp.Query, bool]:
    """Add LIMIT max_rows if missing or larger; keep a smaller literal LIMIT as is."""
    limit = tree.args.get("limit")
    current = None
    if isinstance(limit, exp.Limit) and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        current = int(limit.expression.this)
    elif isinstance(limit, exp.Fetch):  # FETCH FIRST n ROWS ONLY
        count = limit.args.get("count")
        if isinstance(count, exp.Literal) and count.is_int:
            current = int(count.this)
    if current is not None and current <= max_rows:
        return tree, False
    if isinstance(limit, exp.Fetch):
        tree.set("limit", None)
    return tree.limit(max_rows), True


def validate_sql(sql: str, *, dialect: str, allowed_tables: frozenset[str] | set[str], max_rows: int) -> ValidatedSQL:
    """Validate and normalise one query. Raises SQLValidationError with a model-readable reason."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SQLValidationError("empty query")
    tree = _parse_single_query(sql, dialect)
    _check_nodes(tree)
    tables = _check_tables(tree, dialect, allowed_tables)
    tree, limit_applied = _enforce_limit(tree, max_rows)
    return ValidatedSQL(sql=tree.sql(dialect=dialect, pretty=True), tables=tables, limit_applied=limit_applied)
