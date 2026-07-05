"""Subtasks: CRUD routes, two-way status sync, and AI-parse persistence.

Sync contract (user decision, 2026-07):
- checking the last open subtask marks the task done;
- unchecking a subtask of a done task pulls it back to DOING (not todo);
- manually marking the task done auto-checks every subtask;
- adding an open subtask to a done task pulls it back to doing;
- tasks without subtasks are untouched by the sync.
"""

import ai_parser
from conftest import login, StubAIProvider
from models import db, Task, Subtask


def _create_task_with_subtasks(client, titles, status='todo'):
    resp = client.post('/api/tasks', json={
        'title': 'parent', 'subtasks': titles, 'status': status,
    })
    assert resp.status_code == 201
    return resp.get_json()


# ===== creation =====

def test_create_task_with_subtasks(client):
    login(client)
    task = _create_task_with_subtasks(client, ['step one', 'step two'])
    subs = task['subtasks']
    assert [s['title'] for s in subs] == ['step one', 'step two']
    assert [s['position'] for s in subs] == [0, 1]
    assert all(not s['done'] for s in subs)
    assert task['status'] == 'todo'


def test_create_task_skips_blank_subtasks(client):
    login(client)
    task = _create_task_with_subtasks(client, ['  ', 'real', ''])
    assert [s['title'] for s in task['subtasks']] == ['real']


def test_add_subtask_route(client):
    login(client)
    task = _create_task_with_subtasks(client, ['first'])
    resp = client.post(f"/api/tasks/{task['id']}/subtasks", json={'title': 'second'})
    assert resp.status_code == 201
    subs = resp.get_json()['subtasks']
    assert [s['title'] for s in subs] == ['first', 'second']
    assert subs[1]['position'] == 1


def test_add_subtask_requires_title(client):
    login(client)
    task = _create_task_with_subtasks(client, [])
    resp = client.post(f"/api/tasks/{task['id']}/subtasks", json={'title': '   '})
    assert resp.status_code == 400


# ===== two-way sync: subtask direction =====

def test_checking_all_subtasks_marks_task_done(client):
    login(client)
    task = _create_task_with_subtasks(client, ['a', 'b'], status='doing')
    ids = [s['id'] for s in task['subtasks']]

    mid = client.put(f'/api/subtasks/{ids[0]}', json={'done': True}).get_json()
    assert mid['status'] == 'doing'  # one open subtask left

    final = client.put(f'/api/subtasks/{ids[1]}', json={'done': True}).get_json()
    assert final['status'] == 'done'
    assert final['completed'] is True
    assert final['completed_at'] is not None


def test_unchecking_subtask_pulls_done_task_back_to_doing(client):
    login(client)
    task = _create_task_with_subtasks(client, ['a'], status='doing')
    sub_id = task['subtasks'][0]['id']
    assert client.put(f'/api/subtasks/{sub_id}', json={'done': True}).get_json()['status'] == 'done'

    reopened = client.put(f'/api/subtasks/{sub_id}', json={'done': False}).get_json()
    assert reopened['status'] == 'doing'
    assert reopened['completed'] is False
    assert reopened['completed_at'] is None


def test_adding_subtask_to_done_task_reopens_it(client):
    login(client)
    task = _create_task_with_subtasks(client, [], status='done')
    resp = client.post(f"/api/tasks/{task['id']}/subtasks", json={'title': 'more work'})
    body = resp.get_json()
    assert body['status'] == 'doing'
    assert body['subtasks'][0]['done'] is False


def test_deleting_last_open_subtask_completes_task(client):
    login(client)
    task = _create_task_with_subtasks(client, ['done part', 'open part'], status='doing')
    done_id, open_id = task['subtasks'][0]['id'], task['subtasks'][1]['id']
    client.put(f'/api/subtasks/{done_id}', json={'done': True})

    resp = client.delete(f'/api/subtasks/{open_id}')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'done'


def test_deleting_only_subtask_leaves_status_alone(client):
    login(client)
    task = _create_task_with_subtasks(client, ['solo'], status='doing')
    resp = client.delete(f"/api/subtasks/{task['subtasks'][0]['id']}")
    body = resp.get_json()
    assert body['subtasks'] == []
    assert body['status'] == 'doing'  # empty list: sync is a no-op


# ===== two-way sync: manual direction =====

def test_manual_done_checks_all_subtasks(client):
    login(client)
    task = _create_task_with_subtasks(client, ['a', 'b'], status='doing')
    resp = client.put(f"/api/tasks/{task['id']}", json={'status': 'done'})
    body = resp.get_json()
    assert body['status'] == 'done'
    assert all(s['done'] for s in body['subtasks'])


def test_legacy_completed_write_checks_all_subtasks(client):
    login(client)
    task = _create_task_with_subtasks(client, ['a'])
    body = client.put(f"/api/tasks/{task['id']}", json={'completed': True}).get_json()
    assert body['status'] == 'done'
    assert all(s['done'] for s in body['subtasks'])


def test_create_task_done_status_checks_subtasks(client):
    login(client)
    task = _create_task_with_subtasks(client, ['a'], status='done')
    assert all(s['done'] for s in task['subtasks'])


# ===== cascade =====

def test_deleting_task_deletes_its_subtasks(client, app):
    login(client)
    task = _create_task_with_subtasks(client, ['a', 'b'])
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 200
    assert db.session.query(Subtask).count() == 0


# ===== AI parse persists subtasks =====

class StubAIProviderWithSubtasks(StubAIProvider):
    PARSED_TASKS_CANNED = [{
        'title': 'plan trip',
        'priority': 5,
        'space_id': None,
        'deadline': None,
        'estimated_duration': 120,
        'description': 'plan the trip',
        'subtasks': ['book train', 'book hotel'],
    }]


def test_parse_persists_ai_subtasks(client, monkeypatch):
    login(client)
    stub = StubAIProviderWithSubtasks()
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: stub)

    resp = client.post('/api/tasks/parse', json={'text': 'plan trip'})
    assert resp.status_code == 201
    body = resp.get_json()
    assert [s['title'] for s in body['subtasks']] == ['book train', 'book hotel']
    assert all(not s['done'] for s in body['subtasks'])
