"""Context mode — a chat-bar Mode that unplugs the whole Simpler layer.

'Generic' drops the Simpler MCP sidecar's tools, the spaces guidance layer
(and its API round-trip), the workspace-only system-prompt sections and the
workspace slash commands. The domain-agnostic tools (sandbox, extra MCP
servers, natives: web/skills/files) stay in both modes. Selection is per
message (msg.modes), so nothing is persisted and no migration is involved.
"""

import asyncio

import pytest

from chat import assistant_settings, chainlit_app, commands, modes, settings, simpler_client
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


# ===== The mode itself ========================================================

def test_context_mode_options():
    options = modes.build_context_mode_options()
    assert [o['id'] for o in options] == [modes.CONTEXT_SIMPLER, modes.CONTEXT_GENERIC]
    assert options[0]['default'] is True
    assert all(o['icon'] and o['name'] and o['description'] for o in options)


def test_simpler_enabled_defaults_to_on():
    """Unset / unknown / pre-Modes threads keep the historical behavior."""
    assert modes.simpler_context_enabled(None) is True
    assert modes.simpler_context_enabled({}) is True
    assert modes.simpler_context_enabled({'context': ''}) is True
    assert modes.simpler_context_enabled({'model': 'gpt-4o'}) is True
    assert modes.simpler_context_enabled({'context': 'simpler'}) is True
    assert modes.simpler_context_enabled({'context': 'generic'}) is False


def test_context_mode_is_published(instance_root):
    from types import SimpleNamespace

    sent = []

    class Recorder:
        async def set_modes(self, mode_list):
            sent.append(mode_list)

    from chainlit.context import context_var
    token = context_var.set(SimpleNamespace(emitter=Recorder()))
    try:
        run(chainlit_app.publish_modes())
    finally:
        context_var.reset(token)

    mode = next(m for m in sent[0] if m.id == modes.CONTEXT_MODE_ID)
    assert [o.id for o in mode.options] == ['simpler', 'generic']


# ===== Prompt sections ========================================================

def test_marker_sections_selected_per_mode():
    text = ('always here\n'
            '<!-- simpler:start -->\n'
            'workspace only\n'
            '<!-- simpler:end -->\n'
            '<!-- generic:start -->\n'
            'generic only\n'
            '<!-- generic:end -->\n'
            'tail\n')

    kept = assistant_settings.select_prompt_sections(text, simpler=True)
    assert 'workspace only' in kept and 'generic only' not in kept
    assert kept.startswith('always here') and kept.endswith('tail')

    dropped = assistant_settings.select_prompt_sections(text, simpler=False)
    assert 'generic only' in dropped and 'workspace only' not in dropped


def test_marker_free_prompt_is_untouched():
    """Any pre-existing instance override still works verbatim."""
    text = '# My custom prompt\n\nBe terse.'
    assert assistant_settings.select_prompt_sections(text, True) == text
    assert assistant_settings.select_prompt_sections(text, False) == text


def test_html_comments_never_reach_the_model():
    text = '<!--\neditor note\nabout simpler:start markers\n-->\nreal content'
    for simpler in (True, False):
        out = assistant_settings.select_prompt_sections(text, simpler)
        assert out == 'real content'


def test_unclosed_block_fails_closed():
    text = 'kept\n<!-- simpler:start -->\nleaky'
    assert assistant_settings.select_prompt_sections(text, simpler=False) == 'kept'


def test_shipped_prompt_has_both_flavours():
    shipped = open(assistant_settings.shipped_system_prompt_path(),
                   encoding='utf-8').read()
    simpler = assistant_settings.select_prompt_sections(shipped, True)
    generic = assistant_settings.select_prompt_sections(shipped, False)

    assert 'kanban' in simpler and 'kanban' not in generic
    assert 'Injected context' in simpler and 'Injected context' not in generic
    assert 'Context' in generic  # tells the model how to get the workspace back
    # Domain-agnostic sections survive both.
    for keep in ('sandbox__*', 'Delivering files', 'get_file_link'):
        assert keep in simpler and keep in generic


def test_load_system_prompt_honours_the_mode(instance_root):
    write_override(instance_root,
                   'base\n<!-- simpler:start -->\nboard talk\n<!-- simpler:end -->')
    assert 'board talk' in assistant_settings.load_system_prompt()
    assert 'board talk' not in assistant_settings.load_system_prompt(simpler=False)


# ===== Layers: no spaces, no spaces round-trip ================================

def test_generic_mode_skips_spaces_layer_and_api_call(instance_root, monkeypatch):
    write_override(instance_root, 'BASE PROMPT')
    calls = []

    async def fake_list_spaces():
        calls.append(1)
        return [{'id': 1, 'name': 'work', 'context_markdown': 'work guidance here'}]

    monkeypatch.setattr(simpler_client, 'configured', lambda: True)
    monkeypatch.setattr(simpler_client, 'list_spaces', fake_list_spaces)

    prompt = run(chainlit_app.build_system_prompt(None, simpler=False))
    assert 'work guidance here' not in prompt
    assert calls == []  # no round-trip paid for a generic chat

    assert 'work guidance here' in run(chainlit_app.build_system_prompt(None))
    assert calls == [1]


def test_generic_mode_skips_the_api_token_warning(instance_root, monkeypatch):
    """The API_TOKEN remedy block is workspace advice — irrelevant when the
    user deliberately turned the workspace off."""
    write_override(instance_root, 'BASE PROMPT')
    monkeypatch.setattr(simpler_client, 'configured', lambda: False)

    kinds = [layer['kind'] for layer in
             run(chainlit_app.build_system_prompt_layers(simpler=False))]
    assert 'spaces_guidance' not in kinds
    assert 'spaces_guidance' in [
        layer['kind'] for layer in run(chainlit_app.build_system_prompt_layers())]


# ===== Toolbox ================================================================

class FakeServer:
    def __init__(self, name, tool):
        self.name = name
        self._tool = tool

    async def list_tool_specs(self):
        return [{'name': f'{self.name}__{self._tool}', 'description': '',
                 'input_schema': {'type': 'object', 'properties': {}}}]


@pytest.fixture
def fake_servers(monkeypatch):
    servers = [FakeServer('simpler', 'list_tasks'),
               FakeServer('sandbox', 'run_python'),
               FakeServer('extra', 'do_thing')]
    monkeypatch.setattr(chainlit_app, 'preintegrated_servers', lambda: servers)


def test_generic_toolbox_drops_only_the_simpler_sidecar(fake_servers, instance_root):
    names = [s['name'] for s in run(chainlit_app.build_toolbox(simpler=False)).specs()]
    assert 'simpler__list_tasks' not in names
    assert 'sandbox__run_python' in names
    assert 'extra__do_thing' in names
    assert any(n == 'get_file_link' for n in names)  # natives stay
    assert any(n.startswith('load_skill') or 'skill' in n for n in names)


def test_simpler_toolbox_keeps_everything(fake_servers, instance_root):
    names = [s['name'] for s in run(chainlit_app.build_toolbox()).specs()]
    assert 'simpler__list_tasks' in names
    assert 'sandbox__run_python' in names


def test_tools_layer_lists_only_the_tools_actually_sent(instance_root):
    toolbox = Toolbox()
    toolbox.add_native('generic_tool', 'x', {'type': 'object', 'properties': {}},
                       lambda: 'ok')
    prompt = run(chainlit_app.build_system_prompt(toolbox, simpler=False))
    assert 'generic_tool' in prompt


# ===== Slash commands =========================================================

def test_generic_commands_are_the_domain_agnostic_subset():
    assert [c['id'] for c in commands.GENERIC_COMMANDS] == ['skill']
    assert commands.WORKSPACE_COMMAND_IDS == {'task', 'note', 'tasks', 'notes'}
    # Every command is classified — a new one cannot slip through unlabelled.
    assert (commands.WORKSPACE_COMMAND_IDS | commands.GENERIC_COMMAND_IDS
            == {c['id'] for c in commands.COMMANDS})


def test_register_commands_publishes_the_subset(monkeypatch):
    from types import SimpleNamespace

    sent = []

    class Recorder:
        async def set_commands(self, cmds):
            sent.append(cmds)

    monkeypatch.setattr(simpler_client, 'configured', lambda: True)
    from chainlit.context import context_var
    token = context_var.set(SimpleNamespace(emitter=Recorder()))
    try:
        run(chainlit_app.register_commands(simpler=True))
        run(chainlit_app.register_commands(simpler=False))
    finally:
        context_var.reset(token)

    assert [c['id'] for c in sent[0]] == [c['id'] for c in commands.COMMANDS]
    assert [c['id'] for c in sent[1]] == ['skill']
