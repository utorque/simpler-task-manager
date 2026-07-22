"""Issue 003.03 — editable system prompt, read per message (live).

The base prompt comes from instance/assistant/system.md when the user has
edited it in-app, else the shipped chat/prompts/system.md — resolved on
EVERY build_system_prompt call, so edits are live without a restart and
the per-turn layering (date/spaces/tools/skills) stays intact.
"""

import asyncio

import pytest

from chat import assistant_settings, settings, simpler_client
from chat import chainlit_app
from chat.toolbox import Toolbox


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    root = tmp_path / 'instance'
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(root))
    return root


def write_override(instance_root, text):
    override = instance_root / 'assistant' / 'system.md'
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(text)
    return override


def test_build_system_prompt_reads_instance_override(instance_root):
    write_override(instance_root, '# My custom prompt\nBe terse.')
    prompt = run(chainlit_app.build_system_prompt(toolbox=None))
    assert prompt.startswith('# My custom prompt')


def test_build_system_prompt_falls_back_to_shipped(instance_root):
    # The shipped file carries conditional markers (see
    # test_chat_context_mode.py); compare against its resolved Simpler form.
    shipped = assistant_settings.select_prompt_sections(
        open(assistant_settings.shipped_system_prompt_path(),
             encoding='utf-8').read(), simpler=True)
    prompt = run(chainlit_app.build_system_prompt(toolbox=None))
    assert prompt.startswith(shipped.strip()[:40])


def test_edit_between_messages_is_live(instance_root):
    """The override is re-read per call — no module-global staleness."""
    write_override(instance_root, 'FIRST VERSION')
    assert run(chainlit_app.build_system_prompt(None)).startswith('FIRST VERSION')
    write_override(instance_root, 'SECOND VERSION')
    assert run(chainlit_app.build_system_prompt(None)).startswith('SECOND VERSION')
    assistant_settings.reset_system_prompt()
    assert not run(chainlit_app.build_system_prompt(None)).startswith('SECOND VERSION')


def test_build_system_prompt_includes_dynamic_layers(instance_root, monkeypatch):
    write_override(instance_root, 'BASE PROMPT')

    async def fake_list_spaces():
        return [{'id': 1, 'name': 'work', 'context_markdown': 'work guidance here'}]

    monkeypatch.setattr(simpler_client, 'configured', lambda: True)
    monkeypatch.setattr(simpler_client, 'list_spaces', fake_list_spaces)

    toolbox = Toolbox()
    toolbox.add_native('dummy_tool', 'a test tool',
                       {'type': 'object', 'properties': {}}, lambda: 'ok')

    prompt = run(chainlit_app.build_system_prompt(toolbox))
    assert prompt.startswith('BASE PROMPT')
    assert 'Current date and time:' in prompt
    assert 'work guidance here' in prompt
    assert 'dummy_tool' in prompt
    assert '## Skills' in prompt  # bundled skills exist


def test_load_system_prompt_pure_function(instance_root):
    """Importable without Chainlit's runtime and never empty."""
    import inspect
    assert 'chainlit' not in inspect.getsource(assistant_settings)
    text = assistant_settings.load_system_prompt()
    assert isinstance(text, str) and text.strip()

    write_override(instance_root, '# override')
    assert assistant_settings.load_system_prompt() == '# override'
