"""Single-task drag-reorder semantics for POST /api/tasks/reorder.

The old contract ({task_ids: [...]}) rewrote every listed task's priority from
its list position. The new contract nudges ONLY the dragged task:
{task_id, priority} — fractional priorities allowed (the client computes the
midpoint between the drop position's neighbours), clamped to [0, 10]
server-side, audited as a 'reorder' ChangeLog row for that one task.
"""

from conftest import login
from models import db, Task, ChangeLog


def _create_tasks(client, priorities):
    ids = []
    for i, priority in enumerate(priorities):
        resp = client.post('/api/tasks', json={'title': f'task {i}', 'priority': priority})
        assert resp.status_code == 201
        ids.append(resp.get_json()['id'])
    return ids


def test_reorder_changes_only_the_dragged_task(client):
    login(client)
    ids = _create_tasks(client, [8, 5, 2])

    # Drag the p=2 task between the p=8 and p=5 ones -> client sends 6.5.
    resp = client.post('/api/tasks/reorder', json={'task_id': ids[2], 'priority': 6.5})
    assert resp.status_code == 200
    assert resp.get_json()['priority'] == 6.5

    assert db.session.get(Task, ids[0]).priority == 8
    assert db.session.get(Task, ids[1]).priority == 5
    assert db.session.get(Task, ids[2]).priority == 6.5


def test_reorder_writes_a_single_reorder_changelog_row(client):
    login(client)
    ids = _create_tasks(client, [3, 7])

    client.post('/api/tasks/reorder', json={'task_id': ids[0], 'priority': 7.5})

    rows = ChangeLog.query.filter_by(action='reorder').all()
    assert len(rows) == 1
    assert rows[0].entity_id == ids[0]
    assert rows[0].actor == 'user'


def test_reorder_clamps_priority_to_0_10(client):
    login(client)
    ids = _create_tasks(client, [5])

    resp = client.post('/api/tasks/reorder', json={'task_id': ids[0], 'priority': 42})
    assert resp.status_code == 200
    assert resp.get_json()['priority'] == 10

    resp = client.post('/api/tasks/reorder', json={'task_id': ids[0], 'priority': -3})
    assert resp.get_json()['priority'] == 0


def test_reorder_validates_input(client):
    login(client)
    ids = _create_tasks(client, [5])

    assert client.post('/api/tasks/reorder', json={}).status_code == 400
    assert client.post('/api/tasks/reorder', json={'task_id': ids[0]}).status_code == 400
    assert client.post('/api/tasks/reorder', json={'priority': 5}).status_code == 400
    assert client.post('/api/tasks/reorder',
                       json={'task_id': ids[0], 'priority': 'high'}).status_code == 400
    assert client.post('/api/tasks/reorder',
                       json={'task_id': 99999, 'priority': 5}).status_code == 404


def test_fractional_priority_survives_the_roundtrip(client):
    """Priority is a float column now: 4.5 must not truncate to 4."""
    login(client)
    ids = _create_tasks(client, [4])

    client.post('/api/tasks/reorder', json={'task_id': ids[0], 'priority': 4.5})

    resp = client.get('/api/tasks?include_completed=true')
    task = next(t for t in resp.get_json() if t['id'] == ids[0])
    assert task['priority'] == 4.5
