"""Task.status workflow (kanban) route tests — PrePRD 000 decision B.

Invariant under test: `completed ⇔ status == 'done'`, whichever field the
caller writes.
"""

from conftest import login
from models import db, Task


def make_task(client, **overrides):
    body = {'title': 'a task', **overrides}
    resp = client.post('/api/tasks', json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_create_defaults_to_todo(client):
    login(client)
    task = make_task(client)
    assert task['status'] == 'todo'
    assert task['completed'] is False


def test_create_with_explicit_status_persists(client):
    login(client)
    task = make_task(client, status='doing')
    assert task['status'] == 'doing'
    assert db.session.get(Task, task['id']).status == 'doing'


def test_create_with_status_done_flips_completed(client):
    login(client)
    task = make_task(client, status='done')
    assert task['completed'] is True


def test_create_with_invalid_status_is_rejected(client):
    login(client)
    resp = client.post('/api/tasks', json={'title': 'x', 'status': 'in-progress'})
    assert resp.status_code == 400


def test_update_status_to_done_flips_completed(client):
    login(client)
    task = make_task(client)
    resp = client.put(f"/api/tasks/{task['id']}", json={'status': 'done'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'done'
    assert body['completed'] is True


def test_update_status_out_of_done_clears_completed(client):
    login(client)
    task = make_task(client, status='done')
    body = client.put(f"/api/tasks/{task['id']}", json={'status': 'doing'}).get_json()
    assert body['status'] == 'doing'
    assert body['completed'] is False


def test_legacy_completed_write_derives_status(client):
    login(client)
    task = make_task(client, status='doing')
    body = client.put(f"/api/tasks/{task['id']}", json={'completed': True}).get_json()
    assert body['status'] == 'done'
    assert body['completed'] is True

    body = client.put(f"/api/tasks/{task['id']}", json={'completed': False}).get_json()
    assert body['status'] == 'todo'
    assert body['completed'] is False


def test_update_with_invalid_status_is_rejected(client):
    login(client)
    task = make_task(client)
    resp = client.put(f"/api/tasks/{task['id']}", json={'status': 'nope'})
    assert resp.status_code == 400


def test_frozen_is_orthogonal_to_status(client):
    login(client)
    task = make_task(client, status='doing')
    body = client.put(f"/api/tasks/{task['id']}", json={'frozen': True}).get_json()
    assert body['frozen'] is True
    assert body['status'] == 'doing'
