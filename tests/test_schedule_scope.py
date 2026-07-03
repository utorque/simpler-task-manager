"""POST /api/schedule scoping via `task_ids`.

The kanban board sends the currently displayed Doing tasks as `task_ids`;
only those may be (re)scheduled. Tasks outside the scope are left untouched
(their existing slots still block the scoped tasks, like frozen ones).
Without `task_ids` the historical schedule-everything behaviour is unchanged.
"""

from conftest import login


def _create_task(client, title, **overrides):
    payload = {'title': title, 'estimated_duration': 60, **overrides}
    resp = client.post('/api/tasks', json=payload)
    assert resp.status_code == 201
    return resp.get_json()


def _get_task(client, task_id):
    resp = client.get('/api/tasks')
    return next(t for t in resp.get_json() if t['id'] == task_id)


def test_schedule_without_task_ids_schedules_everything(client):
    login(client)
    a = _create_task(client, 'task a')
    b = _create_task(client, 'task b')

    resp = client.post('/api/schedule', json={})
    assert resp.status_code == 200
    assert resp.get_json()['scheduled_tasks'] == 2

    assert _get_task(client, a['id'])['scheduled_start'] is not None
    assert _get_task(client, b['id'])['scheduled_start'] is not None


def test_schedule_with_task_ids_schedules_only_those(client):
    login(client)
    doing = _create_task(client, 'doing task', status='doing')
    todo = _create_task(client, 'todo task')

    resp = client.post('/api/schedule', json={'task_ids': [doing['id']]})
    assert resp.status_code == 200
    assert resp.get_json()['scheduled_tasks'] == 1

    assert _get_task(client, doing['id'])['scheduled_start'] is not None
    assert _get_task(client, todo['id'])['scheduled_start'] is None


def test_schedule_with_empty_task_ids_schedules_nothing(client):
    login(client)
    _create_task(client, 'task a')

    resp = client.post('/api/schedule', json={'task_ids': []})
    assert resp.status_code == 200
    assert resp.get_json()['scheduled_tasks'] == 0


def test_out_of_scope_scheduled_task_keeps_its_slot_and_blocks_it(client):
    login(client)
    scoped = _create_task(client, 'scoped', status='doing')
    other = _create_task(client, 'other')

    # Give `other` a slot first (schedule everything), then reschedule only
    # `scoped`: `other` must keep its slot and `scoped` must not overlap it.
    client.post('/api/schedule', json={})
    other_before = _get_task(client, other['id'])

    resp = client.post('/api/schedule', json={'task_ids': [scoped['id']]})
    assert resp.status_code == 200

    other_after = _get_task(client, other['id'])
    assert other_after['scheduled_start'] == other_before['scheduled_start']
    assert other_after['scheduled_end'] == other_before['scheduled_end']

    scoped_after = _get_task(client, scoped['id'])
    assert scoped_after['scheduled_start'] is not None
    # No overlap with the untouched task's slot.
    assert (scoped_after['scheduled_end'] <= other_after['scheduled_start']
            or scoped_after['scheduled_start'] >= other_after['scheduled_end'])
