"""simpler-mcp: MCP sidecar exposing Simpler's domain as agent tools.

Wraps the Flask REST API over HTTP (PRD 002 §3.1 option A) — zero duplicated
business logic; every route invariant (status⇔completed sync, subtask
two-way sync, audited writes, Fernet mail secrets) rides along for free.
"""
