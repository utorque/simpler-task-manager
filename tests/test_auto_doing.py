"""Auto-select doing: POST /api/tasks/auto-doing.

The user states what they want to work on; the AI (via the raw-completion
`cleanify` seam, reused by ai_parser.select_tasks_with_ai) returns a JSON
array of the matching TODO task ids, and the route moves them to 'doing'.
"""

import json

import ai_parser
from conftest import login, StubAIProvider
from models import db, Task, ChangeLog


class SelectingStub(StubAIProvider):
    """Stub whose raw-completion response (the selection JSON) is scripted.

    Also records the user message so tests can assert candidate framing.
    """

    def __init__(self, response, *a, **kw):
        super().__init__(*a, **kw)
        self.response = response
        self.seen_message = None
        self.seen_prompt = None

    def cleanify(self, note_text, system_prompt):
        self.seen_message = note_text
        self.seen_prompt = system_prompt
        return self.response


def _patch_stub(monkeypatch, response):
    stub = SelectingStub(response)
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)
    return stub


def _create_task(client, title, status='todo', space_id=None):
    resp = client.post('/api/tasks', json={'title': title, 'status': status, 'space_id': space_id})
    assert resp.status_code == 201
    return resp.get_json()['id']


def test_moves_ai_selected_todo_tasks_to_doing(client, monkeypatch):
    login(client)
    website = _create_task(client, 'fix website header')
    groceries = _create_task(client, 'buy groceries')
    stub = _patch_stub(monkeypatch, json.dumps([website]))

    resp = client.post('/api/tasks/auto-doing', json={'text': 'work on the website'})
    assert resp.status_code == 200
    moved = resp.get_json()['moved']
    assert [t['id'] for t in moved] == [website]

    assert db.session.get(Task, website).status == 'doing'
    assert db.session.get(Task, groceries).status == 'todo'
    # The intent and the candidates both reached the AI.
    assert 'work on the website' in stub.seen_message
    assert f'id={website}' in stub.seen_message


def test_move_is_audited_as_ai_actor(client, monkeypatch):
    login(client)
    task_id = _create_task(client, 'fix website header')
    _patch_stub(monkeypatch, json.dumps([task_id]))

    client.post('/api/tasks/auto-doing', json={'text': 'website'})

    row = ChangeLog.query.filter_by(action='update', entity_id=task_id).one()
    assert row.actor == 'ai'
    assert json.loads(row.new_value)['status'] == 'doing'


def test_only_todo_tasks_are_candidates(client, monkeypatch):
    login(client)
    doing = _create_task(client, 'already doing', status='doing')
    blocked = _create_task(client, 'blocked one', status='blocked')
    todo = _create_task(client, 'todo one')
    stub = _patch_stub(monkeypatch, json.dumps([todo]))

    client.post('/api/tasks/auto-doing', json={'text': 'anything'})

    assert f'id={doing}' not in stub.seen_message
    assert f'id={blocked}' not in stub.seen_message
    assert f'id={todo}' in stub.seen_message


def test_space_ids_restricts_candidates(client, monkeypatch):
    login(client)
    in_space = _create_task(client, 'in work space', space_id=1)
    outside = _create_task(client, 'no space task')
    # AI (mis)selecting the out-of-scope id must not move it: it is filtered
    # out because it never was a candidate.
    _patch_stub(monkeypatch, json.dumps([in_space, outside]))

    resp = client.post('/api/tasks/auto-doing', json={'text': 'work stuff', 'space_ids': [1]})
    assert resp.status_code == 200
    assert [t['id'] for t in resp.get_json()['moved']] == [in_space]
    assert db.session.get(Task, outside).status == 'todo'


def test_no_matches_moves_nothing(client, monkeypatch):
    login(client)
    task_id = _create_task(client, 'unrelated')
    _patch_stub(monkeypatch, '[]')

    resp = client.post('/api/tasks/auto-doing', json={'text': 'something else'})
    assert resp.status_code == 200
    assert resp.get_json()['moved'] == []
    assert db.session.get(Task, task_id).status == 'todo'


def test_no_todo_candidates_short_circuits_without_ai(client, monkeypatch):
    login(client)

    def boom():
        raise AssertionError('AI must not be called with no candidates')

    monkeypatch.setattr(ai_parser, 'get_ai_provider', boom)
    resp = client.post('/api/tasks/auto-doing', json={'text': 'anything'})
    assert resp.status_code == 200
    assert resp.get_json()['moved'] == []


def test_unparseable_ai_response_returns_502(client, monkeypatch):
    login(client)
    task_id = _create_task(client, 'a task')
    _patch_stub(monkeypatch, 'sorry, I cannot do that')

    resp = client.post('/api/tasks/auto-doing', json={'text': 'anything'})
    assert resp.status_code == 502
    assert db.session.get(Task, task_id).status == 'todo'


def test_empty_text_is_a_400(client):
    login(client)
    assert client.post('/api/tasks/auto-doing', json={}).status_code == 400
    assert client.post('/api/tasks/auto-doing', json={'text': '  '}).status_code == 400


def test_select_tasks_with_ai_tolerates_fences_and_dict_items(monkeypatch):
    """The seam normalizes fenced output and [{'id': n}] shapes, dedupes, and
    drops non-candidate ids."""
    stub = SelectingStub('```json\n[{"id": 2}, 2, 7, "junk"]\n```')
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)

    candidates = [{'id': 2, 'title': 'a', 'priority': 5},
                  {'id': 3, 'title': 'b', 'priority': 5}]
    assert ai_parser.select_tasks_with_ai('intent', candidates, 'prompt') == [2]
