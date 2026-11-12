"""
The text-to-SQL agent.

    state.py    the state object passed between graph nodes
    charts.py   accepts or rejects the model's chart suggestion
    graph.py    SQLAgent: nodes, routing, and the public ask() method

Usage:
    from app.agent import SQLAgent
    agent = SQLAgent(llm, readonly_engine, max_rows=500, max_attempts=3, timeout_ms=5000)
    result = agent.ask("Which region's revenue dropped last quarter?")
"""

from app.agent.charts import pick_chart
from app.agent.graph import SQLAgent

__all__ = ["SQLAgent", "pick_chart"]
