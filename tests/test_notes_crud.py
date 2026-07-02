"""Issue 001: Notes CRUD + ChangeLog, test-first (RED -> GREEN)."""

from app import db
from models import Note, ChangeLog
from conftest import login


def _create_note(client, space_id=1, **extra):
    payload = {'space_id': space_id}
    payload.update(extra)
    return client.post('/api/notes', json=payload).get_json()


def test_post_note_creates_row_and_changelog(client):
    login(client)
    resp = client.post('/api/notes', json={'space_id': 1, 'content_markdown': 'hello'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['id'] > 0
    assert body['space_id'] == 1
    assert body['content_markdown'] == 'hello'
    # GET list includes it at the top
    resp = client.get('/api/notes?space_id=1')
    assert resp.get_json()[0]['id'] == body['id']
    # ChangeLog row exists
    log = ChangeLog.query.filter_by(
        entity_type='note', entity_id=body['id'], action='create'
    ).first()
    assert log is not None


def test_get_single_note_returns_dto(client):
    login(client)
    body = _create_note(client, title='t', content_markdown='c')
    resp = client.get(f'/api/notes/{body["id"]}')
    assert resp.status_code == 200
    assert resp.get_json() == body


def test_get_missing_note_returns_404(client):
    login(client)
    assert client.get('/api/notes/999999').status_code == 404


def test_delete_note_returns_204_and_logs(client):
    login(client)
    body = _create_note(client, content_markdown='bye')
    resp = client.delete(f'/api/notes/{body["id"]}')
    assert resp.status_code == 204
    log = ChangeLog.query.filter_by(
        entity_type='note', entity_id=body['id'], action='delete'
    ).first()
    assert log is not None
    assert Note.query.get(body['id']) is None


def test_put_note_updates_subset_and_logs(client):
    login(client)
    body = _create_note(client, title='orig', content_markdown='orig')
    resp = client.put(
        f'/api/notes/{body["id"]}',
        json={'title': 'new title'},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['title'] == 'new title'
    assert data['content_markdown'] == 'orig'
    log = ChangeLog.query.filter_by(
        entity_type='note', entity_id=body['id'], action='update'
    ).first()
    assert log is not None


def test_put_note_can_change_space(client):
    login(client)
    body = _create_note(client, space_id=1, content_markdown='x')
    resp = client.put(f'/api/notes/{body["id"]}', json={'space_id': 2})
    assert resp.status_code == 200
    assert resp.get_json()['space_id'] == 2


def test_list_ordered_by_updated_at_desc(client):
    login(client)
    import time
    a = _create_note(client, content_markdown='a')
    time.sleep(0.01)
    b = _create_note(client, content_markdown='b')
    # Touch 'a' so its updated_at becomes the most recent.
    client.put(f'/api/notes/{a["id"]}', json={'content_markdown': 'a2'})
    resp = client.get('/api/notes?space_id=1')
    ids = [n['id'] for n in resp.get_json()]
    assert ids[0] == a['id']
    assert ids[1] == b['id']


def test_list_returns_raw_empty_title(client):
    """Server returns empty title as-is; client renders 'Untitled'."""
    login(client)
    body = _create_note(client, content_markdown='no title here')
    resp = client.get('/api/notes?space_id=1')
    match = [n for n in resp.get_json() if n['id'] == body['id']][0]
    assert match['title'] is None


def test_post_rejects_null_space_id(client):
    login(client)
    resp = client.post('/api/notes', json={'space_id': None, 'content_markdown': 'x'})
    assert resp.status_code in (400, 500)
    assert Note.query.filter_by(content_markdown='x').first() is None


def test_notes_deep_link_redirects_into_unified_shell(client):
    # The Notes destination lives inside the unified shell (index.html);
    # /notes deep-links to it via the #notes hash.
    login(client)
    resp = client.get('/notes')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/#notes')

    # The shell itself carries the Notes view markup.
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'notes-container' in resp.data
    assert b'easymde' in resp.data.lower()
