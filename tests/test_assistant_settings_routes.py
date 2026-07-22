"""Issue 003.07 — the assistant settings panel's backend routes.

/api/assistant/* : model list, reasoning levels, system-prompt override
(edit + reset-to-shipped), skills CRUD (wrapping chat.skills), and the
read-only composition viewer derived from the same layer assembly the model
prompt uses.
"""

import pytest

from conftest import login

from chat import assistant_settings, settings as chat_settings


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    monkeypatch.delenv('CHAT_SKILLS_DIR', raising=False)
    root = tmp_path / 'instance'
    monkeypatch.setattr(chat_settings, 'INSTANCE_DIR', str(root))
    return root


@pytest.fixture
def sclient(client, instance_root):
    login(client)
    return client


def test_get_settings_returns_full_state(sclient):
    response = sclient.get('/api/assistant/settings')
    assert response.status_code == 200
    state = response.get_json()
    assert isinstance(state['models'], list) and state['models']
    assert state['reasoning_levels'] == ['low', 'medium', 'high']
    assert any(s['name'] == 'braindump' and s['source'] == 'bundled'
               for s in state['skills'])
    assert state['system_prompt']['source'] == 'bundled'
    assert state['system_prompt']['body']
    assert state['composition']['layers']


def test_put_models_writes_json(sclient, instance_root):
    response = sclient.put('/api/assistant/models',
                           json=['gpt-4o', 'claude-3-7-sonnet'])
    assert response.status_code == 200
    assert response.get_json()['models'] == ['gpt-4o', 'claude-3-7-sonnet']
    assert assistant_settings.read_models() == ['gpt-4o', 'claude-3-7-sonnet']
    # Validation: at least one model.
    assert sclient.put('/api/assistant/models', json=[]).status_code == 400
    assert sclient.put('/api/assistant/models', json=['  ']).status_code == 400
    assert sclient.put('/api/assistant/models',
                       json={'models': ['x']}).status_code == 400


def test_put_reasoning_levels_writes_json(sclient, instance_root):
    response = sclient.put('/api/assistant/reasoning-levels',
                           json=['low', 'high', 'none'])
    assert response.status_code == 200
    assert assistant_settings.available_reasoning_levels() == ['low', 'high', 'none']
    assert sclient.put('/api/assistant/reasoning-levels', json=[]).status_code == 400


def test_put_system_prompt_writes_override(sclient, instance_root):
    response = sclient.put('/api/assistant/system-prompt',
                           json={'body': '# Custom base prompt'})
    assert response.status_code == 200
    state = response.get_json()
    assert state['source'] == 'instance'
    assert state['last_modified']
    override = instance_root / 'assistant' / 'system.md'
    assert override.read_text() == '# Custom base prompt'
    assert sclient.put('/api/assistant/system-prompt', json={}).status_code == 400


def test_delete_system_prompt_resets_to_shipped(sclient, instance_root):
    sclient.put('/api/assistant/system-prompt', json={'body': 'custom'})
    response = sclient.delete('/api/assistant/system-prompt')
    assert response.status_code == 200
    assert response.get_json()['source'] == 'bundled'
    assert not (instance_root / 'assistant' / 'system.md').exists()


def test_get_system_prompt_reflects_shipped(sclient):
    """The editor gets the file VERBATIM — markers and all. It PUTs this same
    text back, so serving a Context-resolved prompt would delete one flavour
    on the first save."""
    shipped = open(assistant_settings.shipped_system_prompt_path(),
                   encoding='utf-8').read()
    response = sclient.get('/api/assistant/settings')
    body = response.get_json()['system_prompt']['body']
    assert body == shipped
    assert '<!-- simpler:start -->' in body


def test_post_skill_create_calls_skill_function(sclient, instance_root):
    response = sclient.post('/api/assistant/skills',
                            json={'name': 'panelflow', 'description': 'from panel',
                                  'body': '# steps'})
    assert response.status_code == 201
    assert response.get_json()['skill'] == {
        'name': 'panelflow', 'description': 'from panel', 'source': 'instance'}
    assert (instance_root / 'assistant' / 'skills' / 'panelflow' / 'SKILL.md').is_file()
    # Collision with a bundled name -> 400.
    response = sclient.post('/api/assistant/skills',
                            json={'name': 'braindump', 'description': 'x', 'body': 'y'})
    assert response.status_code == 400


def test_put_skill_update_calls_function(sclient, instance_root):
    sclient.post('/api/assistant/skills',
                 json={'name': 'panelflow', 'description': 'd', 'body': 'v1'})
    response = sclient.put('/api/assistant/skills/panelflow', json={'body': 'v2'})
    assert response.status_code == 200
    text = (instance_root / 'assistant' / 'skills' / 'panelflow' / 'SKILL.md').read_text()
    assert 'v2' in text
    # Editing a bundled skill forks it (copy-to-instance-then-edit).
    response = sclient.put('/api/assistant/skills/braindump',
                           json={'body': 'my fork'})
    assert response.status_code == 200
    assert response.get_json()['skill']['source'] == 'instance'
    # Unknown -> 404.
    assert sclient.put('/api/assistant/skills/missing',
                       json={'body': 'x'}).status_code == 404


def test_delete_skill_route_calls_function(sclient, instance_root):
    sclient.post('/api/assistant/skills',
                 json={'name': 'panelflow', 'description': 'd', 'body': 'b'})
    assert sclient.delete('/api/assistant/skills/panelflow').status_code == 200
    assert not (instance_root / 'assistant' / 'skills' / 'panelflow').exists()
    assert sclient.delete('/api/assistant/skills/panelflow').status_code == 404
    assert sclient.delete('/api/assistant/skills/braindump').status_code == 400


def test_composition_viewer_layers(sclient, instance_root):
    layers = sclient.get('/api/assistant/settings').get_json()['composition']['layers']
    kinds = [layer['kind'] for layer in layers]
    assert kinds[:2] == ['base', 'datetime']
    assert 'spaces_guidance' in kinds and 'skills' in kinds
    by_kind = {layer['kind']: layer for layer in layers}
    assert by_kind['base']['name'].endswith('(shipped default)')
    assert by_kind['base']['last_modified']
    # Spaces guidance is built from the DB spaces (seeded defaults).
    assert by_kind['spaces_guidance']['sources']
    assert 'skills' in by_kind and 'braindump' in by_kind['skills']['items']
    # Every layer carries the exact text joined into the model prompt.
    assert all(layer.get('text') for layer in layers)
    # Tools layer present when a toolbox could be built (native tools exist).
    if 'tools' in by_kind:
        assert 'use_skill' in by_kind['tools']['items']


def test_assistant_settings_auth_required(client):
    assert client.get('/api/assistant/settings').status_code == 401
    assert client.put('/api/assistant/models', json=['m']).status_code == 401
    assert client.put('/api/assistant/system-prompt',
                      json={'body': 'x'}).status_code == 401
    assert client.delete('/api/assistant/skills/x').status_code == 401
