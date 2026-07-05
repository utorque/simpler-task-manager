"""Task ← note provenance link (one-way) + creation-time title fallback.

User decisions (2026-07): the link is set when a task is promoted from a note;
clicking the card badge / modal link jumps to the note (frontend); an empty
task title borrows the note's title at creation time AND is backfilled on
every later note save (a task promoted from a still-untitled note stays
title-less until the note gets its # title); deleting the note detaches
linked tasks (note_id → NULL, done in the route because SQLite runs without
PRAGMA foreign_keys).
"""

import ai_parser
from conftest import login, StubAIProvider
from models import db, Task


# ===== POST /api/tasks with note_id =====

def test_create_task_with_note_link(client, sample_note):
    login(client)
    resp = client.post('/api/tasks', json={'title': 'from note', 'note_id': sample_note.id})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['note_id'] == sample_note.id
    assert body['note_title'] == sample_note.title


def test_create_task_empty_title_borrows_note_title(client, sample_note):
    login(client)
    resp = client.post('/api/tasks', json={'title': '  ', 'note_id': sample_note.id})
    assert resp.status_code == 201
    assert resp.get_json()['title'] == sample_note.title


def test_create_task_empty_title_without_note_is_400(client):
    login(client)
    resp = client.post('/api/tasks', json={'title': ''})
    assert resp.status_code == 400


def test_create_task_unknown_note_is_400(client):
    login(client)
    resp = client.post('/api/tasks', json={'title': 'x', 'note_id': 99999})
    assert resp.status_code == 400


def test_create_task_without_note_has_null_link(client):
    login(client)
    body = client.post('/api/tasks', json={'title': 'plain'}).get_json()
    assert body['note_id'] is None
    assert body['note_title'] is None


# ===== promote route tags drafts =====

def test_promote_drafts_carry_note_id(client, sample_note, stub_ai_provider):
    login(client)
    resp = client.post(f'/api/notes/{sample_note.id}/promote-to-task',
                       json={'selected_text': 'buy milk'})
    assert resp.status_code == 200
    drafts = resp.get_json()
    assert all(d['note_id'] == sample_note.id for d in drafts)


class StubAIProviderNoTitle(StubAIProvider):
    PARSED_TASKS_CANNED = [{
        'title': '',
        'priority': 5,
        'space_id': None,
        'deadline': None,
        'estimated_duration': 60,
        'description': 'whatever',
        'subtasks': [],
    }]


def test_promote_draft_without_title_borrows_note_title(client, sample_note, monkeypatch):
    login(client)
    monkeypatch.setattr(ai_parser, 'get_ai_provider', lambda: StubAIProviderNoTitle())
    drafts = client.post(f'/api/notes/{sample_note.id}/promote-to-task',
                         json={'selected_text': 'x'}).get_json()
    assert drafts[0]['title'] == sample_note.title


# ===== note-save title backfill =====

def _untitled_note(client):
    return client.post('/api/notes', json={'space_id': 1, 'title': ''}).get_json()


def test_task_linked_to_untitled_note_may_be_created_titleless(client):
    login(client)
    note = _untitled_note(client)
    resp = client.post('/api/tasks', json={'title': '', 'note_id': note['id']})
    assert resp.status_code == 201
    assert resp.get_json()['title'] == ''


def test_note_save_backfills_titleless_linked_task(client):
    login(client)
    note = _untitled_note(client)
    task_id = client.post('/api/tasks', json={
        'title': '', 'note_id': note['id']}).get_json()['id']

    client.put(f"/api/notes/{note['id']}", json={'title': 'groceries plan'})

    task = db.session.get(Task, task_id)
    assert task.title == 'groceries plan'


def test_note_save_never_overwrites_existing_task_title(client, sample_note):
    login(client)
    task_id = client.post('/api/tasks', json={
        'title': 'my own title', 'note_id': sample_note.id}).get_json()['id']

    client.put(f'/api/notes/{sample_note.id}', json={'title': 'renamed note'})

    assert db.session.get(Task, task_id).title == 'my own title'


def test_untitled_note_save_leaves_task_titleless(client):
    login(client)
    note = _untitled_note(client)
    task_id = client.post('/api/tasks', json={
        'title': '', 'note_id': note['id']}).get_json()['id']

    # Content-only autosave, still no title: nothing to backfill.
    client.put(f"/api/notes/{note['id']}", json={'content_markdown': 'stuff'})

    assert db.session.get(Task, task_id).title == ''


# ===== note deletion detaches (ORM-level SET NULL) =====

def test_deleting_note_nulls_task_link(client, sample_note):
    login(client)
    task_id = client.post('/api/tasks', json={
        'title': 'linked', 'note_id': sample_note.id}).get_json()['id']

    assert client.delete(f'/api/notes/{sample_note.id}').status_code == 204

    task = db.session.get(Task, task_id)
    assert task.note_id is None
    assert task.to_dict()['note_title'] is None
