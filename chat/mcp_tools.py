"""MCP client side of the assistant: expose MCP servers' tools to the model.

Two sources feed the toolbox (chat/toolbox.py):
- pre-integrated servers from env (Simpler's own sidecar first and foremost —
  SIMPLER_MCP_URL — plus any CHAT_MCP_SERVERS entries). These are process-
  wide, connected lazily over streamable HTTP, one short-lived session per
  operation (the sidecar is stateless_http, and per-call sessions survive
  restarts/redeploys of either side).
- servers the user plugs in through Chainlit's native MCP UI; those sessions
  are long-lived and owned by Chainlit (see chainlit_app.py on_mcp_connect).

Tool names are namespaced `<server>__<tool>` so several servers can't clash.
"""

from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from mcp import ClientSession

try:  # mcp >= 1.26: takes a ready httpx.AsyncClient
    from mcp.client.streamable_http import streamable_http_client
    _LEGACY_CLIENT = None
except ImportError:  # older SDKs
    streamable_http_client = None
    from mcp.client.streamable_http import streamablehttp_client as _LEGACY_CLIENT


def result_to_text(result) -> str:
    """Flatten an MCP CallToolResult to model-readable text."""
    parts = []
    for block in getattr(result, 'content', None) or []:
        if getattr(block, 'type', None) == 'text':
            parts.append(block.text)
        else:
            parts.append(f'[{getattr(block, "type", "non-text")} content omitted]')
    text = '\n'.join(p for p in parts if p) or '(empty result)'
    if getattr(result, 'isError', False):
        text = f'TOOL ERROR: {text}'
    return text


def tool_to_spec(tool, server_name: str) -> dict:
    """MCP tool -> the provider-neutral spec chat/providers.py consumes."""
    return {
        'name': f'{server_name}__{tool.name}',
        'description': f'[{server_name}] {tool.description or tool.name}',
        'input_schema': tool.inputSchema or {'type': 'object', 'properties': {}},
    }


class MCPToolServer:
    """A pre-integrated streamable-HTTP MCP server (lazy, per-call sessions).

    `client_factory` is the httpx factory forwarded to the MCP transport —
    tests inject one bound to an in-process ASGI app.
    """

    def __init__(self, name: str, url: str, client_factory=None, timeout: float = 60):
        self.name = name
        self.url = url
        self.client_factory = client_factory
        self.timeout = timeout
        self._specs = None

    def _http_client(self) -> httpx.AsyncClient:
        factory = self.client_factory or (
            lambda **kwargs: httpx.AsyncClient(follow_redirects=True, **kwargs))
        # Long read timeout: tool calls stream over SSE and may work a while.
        return factory(timeout=httpx.Timeout(self.timeout, read=300),
                       headers=None, auth=None)

    @asynccontextmanager
    async def _session(self):
        if streamable_http_client is not None:
            async with self._http_client() as http_client:
                async with streamable_http_client(self.url, http_client=http_client) \
                        as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        yield session
            return
        kwargs = {'timeout': timedelta(seconds=self.timeout)}
        if self.client_factory is not None:
            kwargs['httpx_client_factory'] = self.client_factory
        async with _LEGACY_CLIENT(self.url, **kwargs) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tool_specs(self, refresh: bool = False) -> list[dict]:
        """Namespaced tool specs; cached after the first successful listing
        (the sidecar's tool surface only changes on redeploy)."""
        if self._specs is None or refresh:
            async with self._session() as session:
                listing = await session.list_tools()
            self._specs = [tool_to_spec(t, self.name) for t in listing.tools]
        return self._specs

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        async with self._session() as session:
            result = await session.call_tool(tool_name, arguments or {})
        return result_to_text(result)
