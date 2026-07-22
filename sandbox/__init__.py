"""simpler-sandbox — the assistant's isolated execution environment.

A FastMCP sidecar (server.py) exposing file management + code execution over
a single shared /workspace volume: the web app drops uploaded files there
(CHAT_FILES_DIR), the sandbox works on them, and files it produces are
returned to the user by the assistant after each turn.

The tool implementations (tools.py) are plain functions over a workspace
directory, so the same code backs the dockerized MCP server, the optional
in-process fallback (CHAT_LOCAL_SANDBOX=1), and the test suite.
"""
