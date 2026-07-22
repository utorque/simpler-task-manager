"""Issue 003.04 — model picker migrated from Chat Profiles to Modes.

Model selection is a per-chat Mode (id 'model'): options come from
instance/assistant/models.json (settings panel writes it), falling back to
the CHAT_MODELS/AI_MODEL env chain; the selected value is read per message
from msg.modes and switchable mid-conversation.
"""

import asyncio
from types import SimpleNamespace

import pytest

from chat import assistant_settings, chainlit_app, modes, settings


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    root = tmp_path / 'instance'
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(root))
    return root


def test_model_list_reads_instance_json(instance_root):
    assistant_settings.write_models(['gpt-4o', 'claude-3-7-sonnet'])
    assert assistant_settings.available_models() == ['gpt-4o', 'claude-3-7-sonnet']


def test_model_list_falls_back_to_env(instance_root, monkeypatch):
    monkeypatch.setenv('CHAT_MODELS', 'm1, m2')
    assert assistant_settings.available_models() == ['m1', 'm2']

    monkeypatch.delenv('CHAT_MODELS', raising=False)
    monkeypatch.setenv('AI_MODEL', 'the-env-model')
    assert assistant_settings.available_models() == ['the-env-model']

    monkeypatch.delenv('AI_MODEL', raising=False)
    assert assistant_settings.available_models() == ['gpt-3.5-turbo']

    # An instance models.json beats the env chain; empty file -> env chain.
    monkeypatch.setenv('CHAT_MODELS', 'env-model')
    assistant_settings.write_models(['file-model'])
    assert assistant_settings.available_models() == ['file-model']
    assistant_settings.write_models([])
    assert assistant_settings.available_models() == ['env-model']


def test_build_model_mode_options():
    options = modes.build_model_mode_options(['gpt-4o', 'claude-3-7-sonnet'])
    assert [o['id'] for o in options] == ['gpt-4o', 'claude-3-7-sonnet']
    assert options[0]['default'] is True
    assert all(not o['default'] for o in options[1:])
    assert all(o['icon'] for o in options)  # lucide icon on every option
    assert all(o['name'] for o in options)


def test_selected_model_read_from_message_modes():
    assert modes.current_model_from_modes({'model': 'gpt-4o'}, 'default-m') == 'gpt-4o'
    assert modes.current_model_from_modes({}, 'default-m') == 'default-m'
    assert modes.current_model_from_modes(None, 'default-m') == 'default-m'
    assert modes.current_model_from_modes({'model': ''}, 'default-m') == 'default-m'


def test_on_chat_start_sets_modes(instance_root, monkeypatch):
    assistant_settings.write_models(['m-one', 'm-two'])

    sent = []

    class Recorder:
        async def set_modes(self, mode_list):
            sent.append(mode_list)

        async def set_commands(self, *a, **k):
            pass

    from chainlit.context import context_var
    token = context_var.set(SimpleNamespace(emitter=Recorder()))
    try:
        asyncio.run(chainlit_app.publish_modes())
    finally:
        context_var.reset(token)

    assert len(sent) == 1
    model_mode = next(m for m in sent[0] if m.id == modes.MODEL_MODE_ID)
    assert [o.id for o in model_mode.options] == ['m-one', 'm-two']
    assert model_mode.options[0].default is True


def test_no_chat_profiles_callback_remains():
    import inspect
    source = inspect.getsource(chainlit_app)
    assert 'set_chat_profiles' not in source
    assert 'chat_profile' not in source
