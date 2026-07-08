"""End-to-end sandbox flow, no docker/network:

    toolbox -> MCP client -> sandbox FastMCP server (in-process ASGI)
      -> real subprocess in a tmp workspace -> produced-file detection
         (the chat-side diff that sends files back to the user)

plus the local (non-MCP) fallback registration.
"""

import asyncio
import os

import httpx
import pytest

import sandbox.server as sandbox_srv
from chat.files import new_files_since, snapshot_dir
from chat.mcp_tools import MCPToolServer
from chat.toolbox import Toolbox


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch):
    workspace = str(tmp_path / 'workspace')
    os.makedirs(workspace)
    monkeypatch.setattr(sandbox_srv, 'WORKSPACE', workspace)
    monkeypatch.setattr(sandbox_srv.mcp, '_session_manager', None)
    asgi_app = sandbox_srv.mcp.streamable_http_app()

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi_app),
            base_url='http://sandbox.test',
            headers=headers, timeout=timeout, auth=auth)

    server = MCPToolServer('sandbox', 'http://sandbox.test/mcp',
                           client_factory=client_factory)
    return workspace, server


def test_full_file_roundtrip(sandbox_env):
    workspace, server = sandbox_env

    # An "uploaded" file is already in the workspace before the turn.
    with open(os.path.join(workspace, 'input.csv'), 'w') as f:
        f.write('a,b\n1,2\n3,4\n')
    before = snapshot_dir(workspace)

    async def scenario():
        async with sandbox_srv.mcp.session_manager.run():
            toolbox = Toolbox()
            count = await toolbox.add_mcp_server(server)
            assert count == 6
            listing = await toolbox.execute('sandbox__list_files', {})
            assert 'input.csv' in listing
            return await toolbox.execute('sandbox__run_python', {
                'code': ("import csv\n"
                         "rows = list(csv.reader(open('input.csv')))[1:]\n"
                         "total = sum(int(x) for row in rows for x in row)\n"
                         "open('result.txt', 'w').write(f'total={total}')\n"
                         "print('computed')\n"),
            })
    output = run(scenario())
    assert 'computed' in output

    # The chat side detects exactly the produced file and would return it.
    produced = new_files_since(workspace, before)
    assert [os.path.basename(p) for p in produced] == ['result.txt']
    with open(produced[0]) as f:
        assert f.read() == 'total=10'


def test_local_fallback_registers_same_tool_names(tmp_path):
    from chat import sandbox_tools
    toolbox = Toolbox()
    sandbox_tools.register(toolbox, str(tmp_path))
    names = {spec['name'] for spec in toolbox.specs()}
    assert names == {'sandbox__run_python', 'sandbox__run_shell',
                     'sandbox__list_files', 'sandbox__read_file',
                     'sandbox__write_file', 'sandbox__delete_file'}
    result = run(toolbox.execute('sandbox__write_file',
                                 {'path': 'x.txt', 'content': 'hello'}))
    assert 'wrote' in result
    assert run(toolbox.execute('sandbox__read_file', {'path': 'x.txt'})) == 'hello'
    # Escapes surface as tool errors, not exceptions.
    escaped = run(toolbox.execute('sandbox__read_file', {'path': '../oops'}))
    assert 'TOOL ERROR' in escaped


def test_snapshot_diff_semantics(tmp_path):
    root = str(tmp_path)
    with open(os.path.join(root, 'old.txt'), 'w') as f:
        f.write('old')
    before = snapshot_dir(root)
    assert new_files_since(root, before) == []

    with open(os.path.join(root, 'new.txt'), 'w') as f:
        f.write('new')
    with open(os.path.join(root, 'old.txt'), 'w') as f:
        f.write('modified content')
    changed = {os.path.basename(p) for p in new_files_since(root, before)}
    assert changed == {'new.txt', 'old.txt'}
