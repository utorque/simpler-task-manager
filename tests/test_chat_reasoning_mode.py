"""Issue 003.05 — reasoning effort as a second Mode category.

A 'reasoning' Mode joins 'model' in the chat bar (switchable mid-chat); the
selected level is applied at the provider wire (chat/providers.py) with
provider-specific mapping and a graceful no-op when unset/'none'.
"""

import asyncio
from types import SimpleNamespace

import pytest

from chat import assistant_settings, chainlit_app, modes, providers, settings


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    root = tmp_path / 'instance'
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(root))
    return root


def test_build_reasoning_mode_options():
    options = modes.build_reasoning_mode_options(['low', 'medium', 'high'])
    assert [o['id'] for o in options] == ['low', 'medium', 'high']
    defaults = [o for o in options if o['default']]
    assert [o['id'] for o in defaults] == ['medium']
    assert all(o['icon'] for o in options)

    # 'medium' absent -> first option is the default.
    options = modes.build_reasoning_mode_options(['minimal', 'max'])
    assert options[0]['default'] is True


def test_reasoning_levels_from_instance_json(instance_root):
    assert assistant_settings.available_reasoning_levels() == ['low', 'medium', 'high']
    assistant_settings.write_reasoning_levels(['minimal', 'ultra'])
    assert assistant_settings.available_reasoning_levels() == ['minimal', 'ultra']


def test_on_chat_start_sets_both_modes(instance_root):
    sent = []

    class Recorder:
        async def set_modes(self, mode_list):
            sent.append(mode_list)

    from chainlit.context import context_var
    token = context_var.set(SimpleNamespace(emitter=Recorder()))
    try:
        asyncio.run(chainlit_app.publish_modes())
    finally:
        context_var.reset(token)

    ids = [m.id for m in sent[0]]
    assert modes.MODEL_MODE_ID in ids
    assert modes.REASONING_MODE_ID in ids


def test_current_reasoning_read_from_message():
    assert modes.current_reasoning_from_modes({'reasoning': 'high'}, 'medium') == 'high'
    assert modes.current_reasoning_from_modes({}, 'medium') == 'medium'
    assert modes.current_reasoning_from_modes(None, 'medium') == 'medium'


def test_provider_mappings():
    params = {}
    providers.apply_reasoning_effort(params, 'low', 'openai')
    assert params == {'reasoning_effort': 'low'}

    params = {}
    providers.apply_reasoning_effort(params, 'medium', 'anthropic')
    assert params == {'thinking': {
        'type': 'enabled',
        'budget_tokens': providers.REASONING_BUDGETS['medium'],
    }}
    assert providers.REASONING_BUDGETS['low'] < providers.REASONING_BUDGETS['high']

    # None / 'none' -> graceful no-op for both wire formats.
    for level in (None, 'none'):
        for kind in ('openai', 'anthropic'):
            params = {}
            providers.apply_reasoning_effort(params, level, kind)
            assert params == {}

    # An unknown level on anthropic has no budget mapping -> no-op (the
    # OpenAI wire passes the raw string through; the endpoint may reject it,
    # which on_message surfaces as a provider error).
    params = {}
    providers.apply_reasoning_effort(params, 'mystery', 'anthropic')
    assert params == {}
