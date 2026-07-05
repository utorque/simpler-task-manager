"""MCP tool suite (PRD 002 §3.4) run against the Flask test app.

The sidecar's httpx client is swapped for one with a WSGITransport pointed
at the test app — the exact tool code paths run, the real routes answer, no
network involved. Auth flows through the API_TOKEN bearer path, so every
mutation here also exercises the actor='agent' audit attribution.
"""

import httpx
import pytest

from conftest import login  # noqa: F401  (re-exported fixture helpers)
from models import db, ChangeLog, Note, Task
import mcp_server.server as mcp_srv
from mcp.server.fastmcp.exceptions import ToolError

TOKEN = 'test-mcp-token'


@pytest.fixture
def mcp_client(app, monkeypatch):
    """Point the MCP server's HTTP client at the Flask test app via WSGI."""
    app.config['API_TOKEN'] = TOKEN
    client = httpx.Client(
        transport=httpx.WSGITransport(app=app),
        base_url='http://simpler.test',
        headers={'Authorization': f'Bearer {TOKEN}'},
    )
    monkeypatch.setattr(mcp_srv, '_client', client)
    yield client
    client.close()


# ===== read tools =====

def test_list_spaces_returns_seeded_spaces(mcp_client):
    spaces = mcp_srv.list_spaces()
    names = {s['name'] for s in spaces}
    assert {'work', 'study', 'association'} <= names
    assert all('context_markdown' in s for s in spaces)


def test_list_tasks_filters_space_and_status(mcp_client):
    mcp_srv.create_task(title='w1', space='work')
    mcp_srv.create_task(title='w2', space='work', status='doing')
    mcp_srv.create_task(title='s1', space='study')

    work = mcp_srv.list_tasks(space='work')
    assert {t['title'] for t in work} == {'w1', 'w2'}

    doing = mcp_srv.list_tasks(space='work', status='doing')
    assert [t['title'] for t in doing] == ['w2']

    with pytest.raises(ToolError, match='Invalid status'):
        mcp_srv.list_tasks(status='in-progress')


def test_list_tasks_status_done_implies_completed(mcp_client):
    task = mcp_srv.create_task(title='finished', status='done')
    done = mcp_srv.list_tasks(status='done')
    assert [t['id'] for t in done] == [task['id']]


def test_get_task_and_missing(mcp_client):
    task = mcp_srv.create_task(title='findme', subtasks=['a', 'b'])
    fetched = mcp_srv.get_task(task['id'])
    assert fetched['title'] == 'findme'
    assert [s['title'] for s in fetched['subtasks']] == ['a', 'b']

    with pytest.raises(ToolError, match='not found'):
        mcp_srv.get_task(99999)


def test_workspace_summary_counts_and_overdue(mcp_client):
    mcp_srv.create_task(title='late', deadline='2020-01-01T09:00:00')
    mcp_srv.create_task(title='fine', status='doing')
    mcp_srv.create_task(title='over', status='done', deadline='2020-01-01T09:00:00')

    summary = mcp_srv.get_workspace_summary()
    assert summary['task_counts']['todo'] == 1
    assert summary['task_counts']['doing'] == 1
    assert summary['task_counts']['done'] == 1
    # done tasks are never overdue
    assert [t['title'] for t in summary['overdue_tasks']] == ['late']
    assert {s['name'] for s in summary['spaces']} >= {'work', 'study'}


def test_get_calendar_windows_scheduled_tasks(mcp_client, app):
    from datetime import datetime, timedelta
    task = mcp_srv.create_task(title='slotted')
    soon = datetime.now() + timedelta(hours=2)
    far = datetime.now() + timedelta(days=30)
    with app.app_context():
        row = db.session.get(Task, task['id'])
        row.scheduled_start = soon
        row.scheduled_end = soon + timedelta(minutes=30)
        other = Task(title='distant', scheduled_start=far,
                     scheduled_end=far + timedelta(minutes=30))
        db.session.add(other)
        db.session.commit()

    cal = mcp_srv.get_calendar(days=7)
    assert [t['title'] for t in cal['scheduled_tasks']] == ['slotted']
    assert cal['external_events'] == []


def test_list_changelog_shows_agent_actor(mcp_client):
    task = mcp_srv.create_task(title='logged')
    logs = mcp_srv.list_changelog(limit=10)
    entry = next(l for l in logs if l['entity_type'] == 'task'
                 and l['entity_id'] == task['id'] and l['action'] == 'create')
    assert entry['actor'] == 'agent'


# ===== mutation tools =====

def test_create_task_resolves_space_by_name_and_id(mcp_client):
    by_name = mcp_srv.create_task(title='named', space='Work', priority=7)
    assert by_name['space'] == 'work'
    assert by_name['priority'] == 7

    by_id = mcp_srv.create_task(title='numbered', space=str(by_name['space_id']))
    assert by_id['space_id'] == by_name['space_id']

    with pytest.raises(ToolError, match='Unknown space'):
        mcp_srv.create_task(title='nope', space='atlantis')


def test_move_task_and_invalid_status(mcp_client):
    task = mcp_srv.create_task(title='mover')
    moved = mcp_srv.move_task(task['id'], 'done')
    assert moved['status'] == 'done'
    assert moved['completed'] is True

    back = mcp_srv.move_task(task['id'], 'doing')
    assert back['status'] == 'doing'
    assert back['completed'] is False

    with pytest.raises(ToolError, match='Invalid status'):
        mcp_srv.move_task(task['id'], 'archived')


def test_update_task_clamps_priority_and_requires_fields(mcp_client):
    task = mcp_srv.create_task(title='clamp')
    updated = mcp_srv.update_task(task['id'], priority=25)
    assert updated['priority'] == 10

    with pytest.raises(ToolError, match='No fields'):
        mcp_srv.update_task(task['id'])


def test_subtask_two_way_sync_via_tools(mcp_client):
    task = mcp_srv.create_task(title='parent')
    parent = mcp_srv.add_subtask(task['id'], 'only step')
    sub_id = parent['subtasks'][0]['id']

    checked = mcp_srv.set_subtask(sub_id, done=True)
    assert checked['status'] == 'done'  # last open subtask checked ⇒ done

    reopened = mcp_srv.set_subtask(sub_id, done=False)
    assert reopened['status'] == 'doing'

    remaining = mcp_srv.delete_subtask(sub_id)
    assert remaining['subtasks'] == []


def test_delete_task(mcp_client):
    task = mcp_srv.create_task(title='doomed')
    assert mcp_srv.delete_task(task['id'])['success'] is True
    with pytest.raises(ToolError, match='not found'):
        mcp_srv.get_task(task['id'])


def test_toggle_freeze_and_run_schedule(mcp_client):
    task = mcp_srv.create_task(title='pinned')
    frozen = mcp_srv.toggle_freeze(task['id'])
    assert frozen['frozen'] is True

    result = mcp_srv.run_schedule()
    assert result['success'] is True


def test_update_space_context(mcp_client):
    updated = mcp_srv.update_space_context('work', '- prefer mornings')
    assert updated['context_markdown'] == '- prefer mornings'
    assert updated['name'] == 'work'


def test_create_and_append_note(mcp_client):
    note = mcp_srv.create_note('study', title='journal', content_markdown='# Day 1')
    appended = mcp_srv.append_to_note(note['id'], 'More thoughts.')
    assert appended['content_markdown'] == '# Day 1\n\nMore thoughts.'

    listed = mcp_srv.list_notes(space='study')
    assert [n['id'] for n in listed] == [note['id']]

    fetched = mcp_srv.get_note(note['id'])
    assert fetched['content_markdown'].endswith('More thoughts.')


def test_append_to_empty_note_has_no_leading_blank(mcp_client):
    note = mcp_srv.create_note('work')
    appended = mcp_srv.append_to_note(note['id'], 'first line')
    assert appended['content_markdown'] == 'first line'


def test_draft_tasks_from_text_uses_in_app_parser(mcp_client, stub_ai_provider):
    created = mcp_srv.draft_tasks_from_text('buy milk tomorrow')
    assert [t['title'] for t in created] == ['buy milk']
    logs = mcp_srv.list_changelog(limit=5)
    entry = next(l for l in logs if l['entity_id'] == created[0]['id'])
    assert entry['actor'] == 'ai'  # in-app parse path keeps its explicit actor


def test_mailbox_tools_without_mailboxes(mcp_client):
    assert mcp_srv.list_mailboxes() == []
    with pytest.raises(ToolError, match='No mailboxes'):
        mcp_srv.list_mail()


# ===== auth path =====

def test_tools_fail_cleanly_without_valid_token(app, monkeypatch):
    app.config['API_TOKEN'] = TOKEN
    client = httpx.Client(
        transport=httpx.WSGITransport(app=app),
        base_url='http://simpler.test',
        headers={'Authorization': 'Bearer wrong'},
    )
    monkeypatch.setattr(mcp_srv, '_client', client)
    with pytest.raises(ToolError, match='401'):
        mcp_srv.list_tasks()
    client.close()
