"""Full pre-integrated MCP chain, no network:

    assistant toolbox -> MCP streamable-HTTP client (chat/mcp_tools.py)
      -> simpler-mcp FastMCP server (mcp_server/server.py, in-process ASGI)
        -> Flask REST routes (test app, bearer auth)

This is exactly the production path with both hops swapped for in-process
transports.
"""

import asyncio

import httpx
import pytest

import mcp_server.server as mcp_srv
from chat.mcp_tools import MCPToolServer, result_to_text, tool_to_spec
from chat.toolbox import Toolbox
from models import Task

TOKEN = 'test-mcp-chain-token'


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mcp_server_app(app, monkeypatch):
    """The simpler-mcp ASGI app wired to the Flask test app."""
    app.config['API_TOKEN'] = TOKEN
    sidecar_client = httpx.Client(
        transport=httpx.WSGITransport(app=app),
        base_url='http://simpler.test',
        headers={'Authorization': f'Bearer {TOKEN}'},
    )
    monkeypatch.setattr(mcp_srv, '_client', sidecar_client)
    # The session manager is single-run; force a fresh one per test.
    monkeypatch.setattr(mcp_srv.mcp, '_session_manager', None)
    asgi_app = mcp_srv.mcp.streamable_http_app()
    yield asgi_app
    sidecar_client.close()


@pytest.fixture
def tool_server(mcp_server_app):
    """MCPToolServer whose HTTP layer drives the sidecar ASGI app directly."""
    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_server_app),
            base_url='http://mcp.test',
            headers=headers,
            timeout=timeout,
            auth=auth,
        )
    return MCPToolServer('simpler', 'http://mcp.test/mcp',
                         client_factory=client_factory)


def test_list_tools_namespaced(tool_server):
    async def scenario():
        async with mcp_srv.mcp.session_manager.run():
            return await tool_server.list_tool_specs()
    specs = run(scenario())
    names = {spec['name'] for spec in specs}
    assert 'simpler__create_task' in names
    assert 'simpler__get_workspace_summary' in names
    assert all(spec['input_schema'] is not None for spec in specs)


def test_agent_tool_call_mutates_workspace(app, tool_server):
    async def scenario():
        async with mcp_srv.mcp.session_manager.run():
            toolbox = Toolbox()
            count = await toolbox.add_mcp_server(tool_server)
            assert count > 10
            output = await toolbox.execute('simpler__create_task', {
                'title': 'born via MCP chain',
                'space': 'work',
                'priority': 7,
            })
            summary = await toolbox.execute('simpler__get_workspace_summary', {})
            return output, summary
    output, summary = run(scenario())

    assert 'born via MCP chain' in output
    assert 'task_counts' in summary
    # It really landed in the (test) database.
    task = Task.query.filter_by(title='born via MCP chain').first()
    assert task is not None
    assert task.priority == 7


def test_tool_error_flows_back_as_text(tool_server):
    async def scenario():
        async with mcp_srv.mcp.session_manager.run():
            toolbox = Toolbox()
            await toolbox.add_mcp_server(tool_server)
            return await toolbox.execute('simpler__create_task', {
                'title': 'bad space', 'space': 'no-such-space'})
    output = run(scenario())
    assert 'TOOL ERROR' in output
    assert 'no-such-space' in output


def test_result_to_text_and_spec_helpers():
    class Block:
        type = 'text'
        text = 'hello'

    class Result:
        content = [Block()]
        isError = False

    assert result_to_text(Result()) == 'hello'

    Result.isError = True
    assert result_to_text(Result()).startswith('TOOL ERROR')

    class EmptyResult:
        content = []
        isError = False

    assert result_to_text(EmptyResult()) == '(empty result)'

    class Tool:
        name = 'list_tasks'
        description = 'List tasks'
        inputSchema = {'type': 'object'}

    spec = tool_to_spec(Tool(), 'simpler')
    assert spec['name'] == 'simpler__list_tasks'
    assert spec['description'].startswith('[simpler]')
