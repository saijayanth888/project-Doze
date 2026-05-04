"""LangGraph-based evolution agent.

The public entry point is :func:`agents.runner.start_evolution`, which
launches the graph in an asyncio task and persists every state
transition through :class:`services.lineage_db.LineageDB`.
"""

from agents.runner import request_stop, start_evolution

__all__ = ["request_stop", "start_evolution"]
