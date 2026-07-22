"""Simpler Assistant — the embedded Chainlit chat app (PRD: chainlit refactor).

Replaces the former Hermes integration with a first-party Chainlit app that
shares Simpler's `.env` (AI provider, secret key, API token) and is mounted
same-origin at /assistant by `asgi.py`. Everything under this package is
importable without Chainlit running, so the pure logic (auth bridge, provider
adapters, context building) stays unit-testable with plain pytest.
"""
