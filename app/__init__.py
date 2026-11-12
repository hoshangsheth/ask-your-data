"""
Ask Your Data - natural-language analytics over a SQL database.

Package map (each package has one concern; each module one responsibility):

    app/core       configuration and logging (no business logic)
    app/db         tables, connections, read-only execution, schema catalogue, demo data
    app/sql        static validation of model-generated SQL
    app/llm        provider-agnostic LLM layer (Gemini / Claude / OpenAI adapters + prompts)
    app/agent      the LangGraph text-to-SQL agent (state, nodes, routing, chart choice)
    app/analytics  fixed KPI queries for the dashboard
    app/api        FastAPI wiring: app factory, dependencies, request/response schemas, routes
    app/web        static dashboard (HTML/CSS/JS)

Dependency direction (top may import bottom, never the reverse):

    api -> agent -> llm, sql, db -> core
    api -> analytics -> db -> core

Entry point: `uvicorn app.main:app` (see app/main.py).
"""
