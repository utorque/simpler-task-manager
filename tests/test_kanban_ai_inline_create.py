"""Kanban AI inline-create + inline priority edit (PRD 001).

Covers:
- `/api/tasks/parse` now accepts `force_status` (column placement) and
  `restrict_space` (single-space hard prompt scope).
- `PUT /api/tasks/<id>` clamps `priority` to [0,10] server-side.

Frontend interactions (the priority-badge inline editor) are client-side JS
and not exercised here; they are covered by a manual checklist (see PRD 001
§7.3). The server seams they depend on are anchored below.
"""

import json

import ai_parser
from conftest import login, StubAIProvider
from models import db, Task, ChangeLog


class RecordingStub(StubAIProvider):
    """Captures the system_prompt the route passed to the provider."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen_prompt = None

    def parse_task(self, text, system_prompt):
        self.seen_prompt = system_prompt
        return super().parse_task(text, system_prompt)


# ---------- force_status: column placement (G3, G5) ----------

def test_parse_with_force_status_lands_task_in_that_column(client, stub_ai_provider):
    login(client)
    resp = client.post('/api/tasks/parse', json={
        'text': 'call Marie about the report',
        'force_status': 'doing',
    })
    assert resp.status_code == 201
    body = resp.get_json()
    task = body if isinstance(body, dict) else body[0]
    assert task['status'] == 'doing'
    # actor stays 'ai' (the task was AI-drafted; status override is client placement).
    log = ChangeLog.query.filter_by(entity_type='task', entity_id=task['id']).one()
    assert log.actor == 'ai'
    assert json.loads(log.new_value)['status'] == 'doing'


def test_parse_with_invalid_force_status_is_400_and_creates_nothing(client, stub_ai_provider):
    login(client)
    resp = client.post('/api/tasks/parse', json={
        'text': 'something',
        'force_status': 'bogus',
    })
    assert resp.status_code == 400
    assert Task.query.count() == 0


def test_parse_without_force_status_defaults_to_todo(client, stub_ai_provider):
    login(client)
    resp = client.post('/api/tasks/parse', json={'text': 'buy milk'})
    assert resp.status_code == 201
    task = resp.get_json()
    assert task['status'] == 'todo'


# ---------- restrict_space: single-space hard prompt scope (G2) ----------

def test_parse_with_restrict_space_scopes_prompt_to_one_space(client, monkeypatch):
    login(client)
    stub = RecordingStub()
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)

    resp = client.post('/api/tasks/parse', json={
        'text': 'review notes',
        'restrict_space': 2,  # study
    })
    assert resp.status_code == 201
    assert 'Name: study' in stub.seen_prompt
    assert 'Name: work' not in stub.seen_prompt
    assert 'Name: association' not in stub.seen_prompt


def test_parse_without_restrict_space_sends_all_spaces(client, monkeypatch):
    login(client)
    stub = RecordingStub()
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)

    resp = client.post('/api/tasks/parse', json={'text': 'review notes'})
    assert resp.status_code == 201
    assert 'Name: work' in stub.seen_prompt
    assert 'Name: study' in stub.seen_prompt
    assert 'Name: association' in stub.seen_prompt


def test_parse_with_unresolvable_restrict_space_falls_back_to_all_spaces(client, monkeypatch):
    login(client)
    stub = RecordingStub()
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)

    resp = client.post('/api/tasks/parse', json={
        'text': 'review notes',
        'restrict_space': 999,
    })
    assert resp.status_code == 201
    assert 'Name: work' in stub.seen_prompt
    assert 'Name: study' in stub.seen_prompt
    assert 'Name: association' in stub.seen_prompt


# ---------- multi-task + force_status (G5 edge) ----------

class MultiTaskStub(StubAIProvider):
    def parse_task(self, text, system_prompt):
        return [
            {'title': 'first', 'priority': 3, 'space_id': None, 'deadline': None,
             'estimated_duration': 60, 'description': ''},
            {'title': 'second', 'priority': 3, 'space_id': None, 'deadline': None,
             'estimated_duration': 60, 'description': ''},
        ]


def test_parse_multi_task_with_force_status_applies_to_all(client, monkeypatch):
    login(client)
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: MultiTaskStub())

    resp = client.post('/api/tasks/parse', json={
        'text': 'two things',
        'force_status': 'blocked',
    })
    assert resp.status_code == 201
    tasks = resp.get_json()
    assert isinstance(tasks, list)
    assert len(tasks) == 2
    assert all(t['status'] == 'blocked' for t in tasks)


def test_parse_with_restrict_space_defaults_spaceless_draft_to_scoped_space(client, monkeypatch):
    """US1: typing in a space-filtered board tags the task to that space.

    The stub returns space_id=None (a real LLM would pick the one offered
    space). The route must default such drafts to the scoped space so the new
    task is visible on the filtered board.
    """
    login(client)
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: StubAIProvider())

    resp = client.post('/api/tasks/parse', json={
        'text': 'call Marie',
        'restrict_space': 2,  # study
    })
    assert resp.status_code == 201
    task = resp.get_json()
    assert task['space_id'] == 2


# ---------- priority clamp (G4, T11) ----------

def _make_task(app):
    task = Task(title='clamp me', priority=5)
    db.session.add(task)
    db.session.commit()
    return task


def test_update_priority_clamps_high_value(client, app):
    login(client)
    task = _make_task(app)
    resp = client.put(f'/api/tasks/{task.id}', json={'priority': 42})
    assert resp.status_code == 200
    assert resp.get_json()['priority'] == 10
    assert db.session.get(Task, task.id).priority == 10


def test_update_priority_clamps_low_value(client, app):
    login(client)
    task = _make_task(app)
    resp = client.put(f'/api/tasks/{task.id}', json={'priority': -3})
    assert resp.status_code == 200
    assert resp.get_json()['priority'] == 0
    assert db.session.get(Task, task.id).priority == 0


def test_update_priority_normal_value_is_unchanged(client, app):
    login(client)
    task = _make_task(app)
    resp = client.put(f'/api/tasks/{task.id}', json={'priority': 8})
    assert resp.status_code == 200
    assert resp.get_json()['priority'] == 8


def test_update_priority_writes_audit_row_actor_user(client, app):
    login(client)
    task = _make_task(app)
    client.put(f'/api/tasks/{task.id}', json={'priority': 7})
    log = ChangeLog.query.filter_by(
        entity_type='task', entity_id=task.id, action='update'
    ).order_by(ChangeLog.id.desc()).first()
    assert log is not None
    assert log.actor == 'user'
    assert json.loads(log.new_value)['priority'] == 7
