"""Perslis Symbolic Floor — runtime.

Executes symbolic tools that the Perslis admission gate already admitted and
signed. It cannot admit one itself: the gate is not part of this package and
never runs on your machine. What you have here is an executor, complete for
execution: CSV/JSON/SQLite in, exact answers out, over MCP.

Offline. No network. No model. No telemetry. Standard library only.
"""
__version__ = "1.1.2"
