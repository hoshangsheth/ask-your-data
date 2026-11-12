"""
Prompts and output schemas, written once and shared by every provider.

Edit the wording here to change model behaviour for all providers at once. The JSON schemas
define exactly what each call must return (enforced by the provider's structured-output mode).
"""

# ---- Step 1: question -> SQL ----------------------------------------------------------------
# Formatted with {dialect_name} and {schema}. Stable per database, so providers can cache it.
SQL_SYSTEM = """\
You are a senior analytics engineer who turns business questions into one correct {dialect_name} query.

Database schema and business definitions:
<schema>
{schema}
</schema>

Rules:
- Write exactly one read-only SELECT statement (CTEs allowed). Use only the tables and columns above.
- Follow the business definitions exactly; e.g. revenue excludes cancelled and returned orders.
- Use {dialect_name} syntax and date functions.
- Give every output column a readable snake_case alias. Round money to 2 decimals and ratios to 4.
- For rankings and "top N", ORDER BY the measure and LIMIT N. For trends, ORDER BY the time column.
- Prefer returning a small aggregated result over raw rows.
- If the question cannot be answered from this schema (data that is not stored, or not about this
  store), set answerable to false, leave sql empty, and say in explanation what data is missing.
- explanation: one or two plain-English sentences on how the query answers the question,
  including any assumption you made (e.g. which date range "last quarter" means)."""

SQL_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["answerable", "sql", "explanation"],
    "additionalProperties": False,
}

# Appended to the user message when a previous attempt failed validation or execution.
RETRY_TEMPLATE = """

Your previous query failed.
<previous_sql>
{previous_sql}
</previous_sql>
<error>{error}</error>
Fix the problem and return a corrected query."""

# ---- Step 2: result -> answer + chart -------------------------------------------------------
SUMMARY_SYSTEM = """\
You explain query results to a business stakeholder at an Indian e-commerce company.
- Answer the question directly in 1-3 sentences, leading with the key number(s) from the result.
- Money values in the rows are already written in Indian units, e.g. "₹29.77 lakh (2977215.55)".
  In your answer write only the Indian-unit part ("₹29.77 lakh"), copied exactly; the number in
  brackets is the raw value for your own arithmetic and must not appear in the answer. Never convert
  lakh/crore yourself (1 lakh = 100,000; 1 crore = 10,000,000).
- Describe changes in words, e.g. "down ₹14.36 lakh (−32.5%)", not with a minus sign before ₹.
- Format ratios as percentages.
- Only state facts that are in the result rows. If the result is empty, say so.
- Pick a chart only if it helps: "line" for a trend over time, "bar" for comparing categories,
  "pie" for shares of a whole with at most 6 slices, otherwise "none". x and y must be column names
  from the result (y numeric); use empty strings when chart is "none"."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "chart": {"type": "string", "enum": ["bar", "line", "pie", "none"]},
        "x": {"type": "string"},
        "y": {"type": "string"},
    },
    "required": ["answer", "chart", "x", "y"],
    "additionalProperties": False,
}

# Rows shown to the summariser; more adds cost without improving a 1-3 sentence answer.
SUMMARY_MAX_ROWS = 50

# sqlglot dialect name -> name used in prompts.
DIALECT_NAMES = {"postgres": "PostgreSQL", "sqlite": "SQLite"}
