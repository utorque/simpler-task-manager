"""Space AI context: user-editable markdown injected into every AI task
prompt as guidance only (guide, not source).
"""

import ai_parser
from conftest import login, StubAIProvider
from models import db, Space
from prompt_context import build_email_to_task_prompt, build_task_parse_prompt, space_guidance_block


def set_context(space_id, markdown):
    space = db.session.get(Space, space_id)
    space.context_markdown = markdown
    db.session.commit()
    return space


def test_context_markdown_roundtrips_through_the_api(client):
    login(client)
    created = client.post('/api/spaces', json={
        'name': 'side-project',
        'context_markdown': '## Stack\nFlask + SQLite. Deadlines are soft.',
    }).get_json()
    assert created['context_markdown'].startswith('## Stack')

    updated = client.put(f"/api/spaces/{created['id']}",
                         json={'context_markdown': 'rewritten'}).get_json()
    assert updated['context_markdown'] == 'rewritten'

    listed = client.get('/api/spaces').get_json()
    assert any(s['context_markdown'] == 'rewritten' for s in listed)


def test_no_context_means_no_guidance_block(app):
    # Seeded spaces have no context — prompts stay byte-identical to before.
    assert space_guidance_block() == ""
    assert 'SPACE CONTEXT' not in build_task_parse_prompt()


def test_guidance_block_frames_context_as_guide_not_source(app):
    set_context(1, 'Boss is Alice. Reports are always priority 8+.')

    block = space_guidance_block()
    assert '### Space: work' in block
    assert 'Reports are always priority 8+.' in block
    # The framing the feature is about: guidance only, never task content.
    assert 'guidance' in block.lower()
    assert 'never copy' in block.lower()
    assert 'a guide, not a source' in block.lower()

    # Both task-prompt builders carry it, after the spaces list.
    for prompt in (build_task_parse_prompt(), build_email_to_task_prompt()):
        assert 'Available spaces:' in prompt
        assert '--- SPACE CONTEXT (guidance only) ---' in prompt
        assert prompt.index('Available spaces:') < prompt.index('SPACE CONTEXT')


def test_only_spaces_with_context_appear(app):
    set_context(2, 'Exam session in July.')
    block = space_guidance_block()
    assert '### Space: study' in block
    assert '### Space: work' not in block
    assert '### Space: association' not in block


def test_parse_route_sends_guidance_to_the_provider(client, monkeypatch):
    login(client)
    set_context(1, 'Work tasks default to 30 minutes.')

    seen = {}

    class RecordingStub(StubAIProvider):
        def parse_task(self, text, system_prompt):
            seen['system_prompt'] = system_prompt
            return super().parse_task(text, system_prompt)

    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: RecordingStub())

    resp = client.post('/api/tasks/parse', json={'text': 'call the plumber'})
    assert resp.status_code == 201
    assert 'Work tasks default to 30 minutes.' in seen['system_prompt']
    assert '--- SPACE CONTEXT (guidance only) ---' in seen['system_prompt']


# --- restrict_space: single-space hard prompt scoping (PRD 001, G2) ---

def _set_all_contexts():
    set_context(1, 'Work context marker W.')
    set_context(2, 'Study context marker S.')
    set_context(3, 'Association context marker A.')


def test_restrict_space_by_id_lists_only_that_space(app):
    _set_all_contexts()
    prompt = build_task_parse_prompt(restrict_space=2)
    # The "Available spaces" block lists ONLY the restricted space.
    assert 'Name: study' in prompt
    assert 'Name: work' not in prompt
    assert 'Name: association' not in prompt
    # The space-guidance block carries ONLY that space's context.
    assert 'Study context marker S.' in prompt
    assert 'Work context marker W.' not in prompt
    assert 'Association context marker A.' not in prompt


def test_restrict_space_by_name_matches_id_behaviour(app):
    _set_all_contexts()
    prompt = build_task_parse_prompt(restrict_space='Study')
    assert 'Name: study' in prompt
    assert 'Name: work' not in prompt
    assert 'Name: association' not in prompt
    assert 'Study context marker S.' in prompt
    assert 'Work context marker W.' not in prompt


def test_restrict_space_omitted_is_all_spaces(app):
    _set_all_contexts()
    prompt = build_task_parse_prompt()
    assert 'Name: work' in prompt
    assert 'Name: study' in prompt
    assert 'Name: association' in prompt


def test_restrict_space_none_is_all_spaces(app):
    _set_all_contexts()
    prompt = build_task_parse_prompt(restrict_space=None)
    assert 'Name: work' in prompt
    assert 'Name: study' in prompt
    assert 'Name: association' in prompt


def test_restrict_space_unresolvable_falls_back_to_all_spaces(app, caplog):
    _set_all_contexts()
    prompt = build_task_parse_prompt(restrict_space=999)
    assert 'Name: work' in prompt
    assert 'Name: study' in prompt
    assert 'Name: association' in prompt
