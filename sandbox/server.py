"""simpler-sandbox — FastMCP server exposing the sandbox tools.

Runs in its own container (see sandbox/Dockerfile + docker-compose.yml):
no app secrets, its own filesystem, resource limits, network off by
default. The ONLY thing it shares with the app is the /workspace volume —
uploaded files arrive there, produced files are picked up from there.

Config (env):
  SANDBOX_WORKSPACE  the shared workspace directory (default /workspace)
  MCP_BIND           host:port to serve on          (default 0.0.0.0:8766)

Transport: streamable HTTP at /mcp (stateless), mirroring mcp_server/.
"""

import os

from mcp.server.fastmcp import FastMCP

from sandbox import tools

WORKSPACE = os.getenv('SANDBOX_WORKSPACE', '/workspace')
MCP_BIND = os.getenv('MCP_BIND', '0.0.0.0:8766')

_bind_host, _, _bind_port = MCP_BIND.partition(':')

mcp = FastMCP(
    'sandbox',
    instructions=(
        'An isolated execution sandbox sharing one /workspace directory '
        'with the assistant: files the user uploads appear here, and files '
        'you create in the workspace are returned to the user after your '
        'turn. No state persists between calls — pass data via files. '
        'Paths are relative to the workspace root.'
    ),
    host=_bind_host or '0.0.0.0',
    port=int(_bind_port or 8766),
    stateless_http=True,
)


@mcp.tool()
def run_python(code: str, timeout: int = 60) -> str:
    """Execute a Python snippet (cwd = the shared workspace; pandas, numpy,
    matplotlib, openpyxl, pillow, pypdf preinstalled). Returns exit code +
    stdout/stderr. Save results as files in the workspace to return them to
    the user; print() what you need to see. `timeout` is in seconds (max 300).
    """
    return tools.run_python(WORKSPACE, code, timeout)


@mcp.tool()
def run_shell(command: str, timeout: int = 60) -> str:
    """Execute a shell command (cwd = the shared workspace). Returns exit
    code + stdout/stderr. `timeout` in seconds (max 300)."""
    return tools.run_shell(WORKSPACE, command, timeout)


@mcp.tool()
def list_files(path: str = '.') -> str:
    """List workspace files (recursive, sizes, dotfiles hidden), `path`
    relative to the workspace root."""
    return tools.list_files(WORKSPACE, path)


@mcp.tool()
def read_file(path: str, max_chars: int = 20000) -> str:
    """Read a text file from the workspace (truncated at `max_chars`)."""
    return tools.read_file(WORKSPACE, path, max_chars)


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write/overwrite a text file in the workspace (parent directories are
    created). Files in the workspace are returned to the user after the turn."""
    return tools.write_file(WORKSPACE, path, content)


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file or directory (recursively) inside the workspace."""
    return tools.delete_file(WORKSPACE, path)


def main():
    os.makedirs(WORKSPACE, exist_ok=True)
    mcp.run(transport='streamable-http')


if __name__ == '__main__':
    main()
