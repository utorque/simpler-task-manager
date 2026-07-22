"""Issue 003.10 — model file delivery.

The auto-attach-after-turn block is gone; the model delivers files
explicitly, either with the `attach_file_to_answer` tool (rich Chainlit
download chip, queued and flushed after the turn) or by emitting relative
`/api/workspace/files/workspace/<rel>` markdown links documented in the
system prompt.
"""

import asyncio
import inspect

import pytest

from chat import chainlit_app, files
from chat.toolbox import Toolbox


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    root.mkdir()
    monkeypatch.setenv('CHAT_FILES_DIR', str(root))
    return root


def run(coro):
    return asyncio.run(coro)


def test_attach_file_tool_spec_registered(store):
    toolbox = Toolbox()
    files.register(toolbox, str(store), queue=[])
    spec = next(s for s in toolbox.specs() if s['name'] == 'attach_file_to_answer')
    assert spec['input_schema']['properties'] == {
        'path': {'type': 'string',
                 'description': spec['input_schema']['properties']['path']['description']}}
    assert spec['input_schema']['required'] == ['path']


def test_attach_file_tool_returns_confirmation(store):
    (store / 'report.pdf').write_bytes(b'%PDF')
    toolbox = Toolbox()
    queue = []
    files.register(toolbox, str(store), queue)

    output = run(toolbox.execute('attach_file_to_answer', {'path': 'report.pdf'}))
    assert not output.startswith('TOOL ERROR')
    assert 'report.pdf' in output

    output = run(toolbox.execute('attach_file_to_answer', {'path': 'missing.pdf'}))
    assert output.startswith('TOOL ERROR')
    assert 'not found' in output


def test_attach_file_tool_enqueues_element(store):
    """The tool queues the resolved path; on_message flushes the queue as
    cl.File elements after run_agent returns (the scheduling mechanism,
    not Chainlit's send, is what's pinned here)."""
    (store / 'out' ).mkdir()
    (store / 'out' / 'data.csv').write_text('a,b')
    toolbox = Toolbox()
    queue = []
    files.register(toolbox, str(store), queue)

    run(toolbox.execute('attach_file_to_answer', {'path': 'out/data.csv'}))
    assert queue == [str(store / 'out' / 'data.csv')]
    # Absolute in-workspace paths (as printed in attachment context) work too;
    # re-attaching is idempotent.
    run(toolbox.execute('attach_file_to_answer',
                        {'path': str(store / 'out' / 'data.csv')}))
    assert len(queue) == 1


def test_attach_file_tool_rejects_escape(store, tmp_path):
    secret = tmp_path / 'secret.txt'
    secret.write_text('nope')
    toolbox = Toolbox()
    queue = []
    files.register(toolbox, str(store), queue)
    for attack in ('../secret.txt', str(secret), '/etc/passwd', 'a\\b'):
        output = run(toolbox.execute('attach_file_to_answer', {'path': attack}))
        assert output.startswith('TOOL ERROR'), attack
    assert queue == []


def test_auto_attach_removed_from_on_message():
    source = inspect.getsource(chainlit_app.on_message)
    assert 'new_files_since' not in source
    assert 'snapshot_dir' not in source
    assert 'Files from this turn' not in source


def test_system_prompt_documents_inline_link_convention(tmp_path, monkeypatch):
    from chat import settings
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(tmp_path / 'instance'))
    prompt = run(chainlit_app.build_system_prompt(toolbox=None))
    assert '/api/workspace/files/workspace/' in prompt
    assert 'attach_file_to_answer' in prompt
    # The old auto-send promise is gone.
    assert 'automatically sent back' not in prompt
