"""Model file delivery.

The auto-attach-after-turn block is gone and the model can no longer attach
raw files: it delivers files by LINK only. The `get_file_link` tool validates
a workspace path and returns a ready-to-embed markdown download link using the
`/api/workspace/files/workspace/<rel>` convention documented in the system
prompt. The link lives in the reply text, so it persists across thread reloads
with no blob-storage provider.
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


def test_file_link_tool_spec_registered(store):
    toolbox = Toolbox()
    files.register(toolbox, str(store))
    spec = next(s for s in toolbox.specs() if s['name'] == 'get_file_link')
    assert spec['input_schema']['properties'] == {
        'path': {'type': 'string',
                 'description': spec['input_schema']['properties']['path']['description']}}
    assert spec['input_schema']['required'] == ['path']


def test_file_link_tool_returns_markdown_link(store):
    (store / 'report.pdf').write_bytes(b'%PDF')
    toolbox = Toolbox()
    files.register(toolbox, str(store))

    output = run(toolbox.execute('get_file_link', {'path': 'report.pdf'}))
    assert not output.startswith('TOOL ERROR')
    assert '[report.pdf](/api/workspace/files/workspace/report.pdf)' in output

    output = run(toolbox.execute('get_file_link', {'path': 'missing.pdf'}))
    assert output.startswith('TOOL ERROR')
    assert 'not found' in output


def test_file_link_tool_builds_nested_and_encoded_url(store):
    """Nested paths keep their `/` separators; spaces/unicode are
    percent-encoded so the link is valid markdown."""
    (store / 'out').mkdir()
    (store / 'out' / 'my report.csv').write_text('a,b')
    toolbox = Toolbox()
    files.register(toolbox, str(store))

    output = run(toolbox.execute('get_file_link', {'path': 'out/my report.csv'}))
    assert '/api/workspace/files/workspace/out/my%20report.csv' in output

    # Absolute in-workspace paths (as printed in attachment context) work too.
    output = run(toolbox.execute(
        'get_file_link', {'path': str(store / 'out' / 'my report.csv')}))
    assert '/api/workspace/files/workspace/out/my%20report.csv' in output


def test_file_link_tool_rejects_escape(store, tmp_path):
    secret = tmp_path / 'secret.txt'
    secret.write_text('nope')
    toolbox = Toolbox()
    files.register(toolbox, str(store))
    for attack in ('../secret.txt', str(secret), '/etc/passwd', 'a\\b'):
        output = run(toolbox.execute('get_file_link', {'path': attack}))
        assert output.startswith('TOOL ERROR'), attack


def test_no_raw_file_attachment_in_on_message():
    """The model delivers by link only — on_message no longer flushes a
    cl.File download chip after the turn."""
    source = inspect.getsource(chainlit_app.on_message)
    assert 'cl.File' not in source
    assert 'new_files_since' not in source
    assert 'snapshot_dir' not in source
    assert 'Files from this turn' not in source


def test_system_prompt_documents_link_delivery(tmp_path, monkeypatch):
    from chat import settings
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(tmp_path / 'instance'))
    prompt = run(chainlit_app.build_system_prompt(toolbox=None))
    assert '/api/workspace/files/workspace/' in prompt
    assert 'get_file_link' in prompt
    # The old chip-attachment path is gone from the model's instructions.
    assert 'attach_file_to_answer' not in prompt
    assert 'automatically sent back' not in prompt
