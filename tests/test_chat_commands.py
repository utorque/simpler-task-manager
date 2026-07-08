"""chat/commands.py + chat/simpler_client.py against the REAL Flask API.

Mirrors tests/test_mcp_tools.py: the assistant's async httpx client is
swapped for one driving the Flask test app in-process (WSGI wrapped as ASGI
via a2wsgi), so the exact command code paths run against the real routes —
bearer auth included — with no network.
"""

import asyncio

import httpx
import pytest
from a2wsgi import WSGIMiddleware

import chat.simpler_client as simpler_client
from chat import commands
from models import db, Note, Task

TOKEN = 'test-assistant-token'


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def assistant_client(app, monkeypatch):
    app.config['API_TOKEN'] = TOKEN
    monkeypatch.setenv('API_TOKEN', TOKEN)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=WSGIMiddleware(app)),
        base_url='http://simpler.test',
        headers={'Authorization': f'Bearer {TOKEN}'},
    )
    monkeypatch.setattr(simpler_client, '_client', client)
    yield client
    run(client.aclose())


@pytest.fixture
def seeded_tasks(app):
    note = Note(space_id=1, title='meeting notes', content_markdown='remember the slides')
    db.session.add(note)
    db.session.flush()
    doing = Task(title='Write report', status='doing', space_id=1, note_id=note.id)
    todo = Task(title='Buy milk', status='todo', space_id=2)
    db.session.add_all([doing, todo])
    db.session.commit()
    return {'note': note.id, 'doing': doing.id, 'todo': todo.id}


def test_unconfigured_token_degrades_gracefully(app, monkeypatch):
    monkeypatch.delenv('API_TOKEN', raising=False)
    block, error = run(commands.handle_command('tasks', '', None))
    assert block is None
    assert 'not configured' in error


def test_task_command_injects_task_and_linked_note(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command(
        'task', f"#{seeded_tasks['doing']} let's go", None))
    assert error is None
    assert f"Task #{seeded_tasks['doing']}: Write report" in block
    # House rule: an injected task brings its linked note's CONTENT along.
    assert 'meeting notes' in block
    assert 'remember the slides' in block


def test_task_command_resolves_by_title(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command('task', 'milk', None))
    assert error is None
    assert 'Buy milk' in block


def test_task_command_without_ref_lists_open_tasks(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command('task', '', None))
    assert error is None
    assert 'Write report' in block and 'Buy milk' in block


def test_task_command_no_match_offers_board(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command('task', 'zzz-nothing', None))
    assert error is None
    assert 'No task matched' in block
    assert 'Write report' in block


def test_tasks_command_respects_space_filter(assistant_client, seeded_tasks):
    block, _ = run(commands.handle_command('tasks', '', [1]))
    assert 'Write report' in block
    assert 'Buy milk' not in block
    assert 'selected spaces' in block

    block_all, _ = run(commands.handle_command('tasks', '', None))
    assert 'Buy milk' in block_all


def test_note_command_injects_full_content(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command('note', 'meeting', None))
    assert error is None
    assert 'remember the slides' in block


def test_notes_command_lists_titles(assistant_client, seeded_tasks):
    block, error = run(commands.handle_command('notes', '', None))
    assert error is None
    assert 'meeting notes' in block


def test_unknown_command_errors():
    block, error = run(commands.handle_command('frobnicate', '', None))
    assert block is None
    assert 'Unknown command' in error


def test_build_starters_doing_tasks_first():
    doing = [{'id': 5, 'title': 'Ship the thing'}]
    starters = commands.build_starters(doing)
    assert starters[0]['command'] == 'task'
    assert '#5' in starters[0]['message']
    assert 'Ship the thing' in starters[0]['label']
    # Generic starters follow.
    assert any(s['command'] is None for s in starters)


def test_build_starters_limits_and_works_empty():
    many = [{'id': i, 'title': f't{i}'} for i in range(20)]
    starters = commands.build_starters(many)
    task_starters = [s for s in starters if s['command'] == 'task']
    assert len(task_starters) == 6
    assert commands.build_starters([])  # generic ones only, never empty
