"""Public read-only note sharing: share/unshare API + the /n/<token> page.

The share is the note's single public credential (one NoteShare per note). The
public page is built server-side on every request, so it always renders the
note's latest saved markdown; revoking the share (or deleting the note) 404s
the link.
"""

from app import db
from models import Note, NoteShare, ChangeLog
from conftest import login


def _create_note(client, space_id=1, **extra):
    payload = {'space_id': space_id}
    payload.update(extra)
    return client.post('/api/notes', json=payload).get_json()


def _share(client, note_id):
    return client.post(f'/api/notes/{note_id}/share')


# ===== share creation =====

def test_share_creates_token_and_logs(client):
    login(client)
    note = _create_note(client, content_markdown='hello')
    resp = _share(client, note['id'])
    assert resp.status_code == 200
    token = resp.get_json()['token']
    assert token
    # The note DTO now advertises the token.
    dto = client.get(f'/api/notes/{note["id"]}').get_json()
    assert dto['public_share_token'] == token
    # A NoteShare row exists, and a 'share' ChangeLog was recorded.
    assert NoteShare.query.filter_by(note_id=note['id']).first().token == token
    assert ChangeLog.query.filter_by(
        entity_type='note', entity_id=note['id'], action='share').first() is not None


def test_share_is_idempotent(client):
    login(client)
    note = _create_note(client, content_markdown='hi')
    first = _share(client, note['id']).get_json()['token']
    second = _share(client, note['id']).get_json()['token']
    assert first == second
    assert NoteShare.query.filter_by(note_id=note['id']).count() == 1


def test_unshared_note_has_null_token(client):
    login(client)
    note = _create_note(client, content_markdown='x')
    assert client.get(f'/api/notes/{note["id"]}').get_json()['public_share_token'] is None


def test_share_missing_note_404(client):
    login(client)
    assert _share(client, 999999).status_code == 404


# ===== the public page =====

def test_public_page_renders_latest_markdown_no_auth(client):
    login(client)
    note = _create_note(client, title='Shared', content_markdown='first version')
    token = _share(client, note['id']).get_json()['token']

    # A fresh client with NO session cookie can read it.
    anon = client.application.test_client()
    resp = anon.get(f'/n/{token}')
    assert resp.status_code == 200
    assert b'first version' in resp.data
    assert b'easymde' in resp.data.lower()          # read-only EasyMDE mounted
    assert b'publicNoteEditor' in resp.data

    # Latest-version guarantee: edit the note, re-fetch the SAME url.
    client.put(f'/api/notes/{note["id"]}', json={'content_markdown': 'second version'})
    resp = anon.get(f'/n/{token}')
    assert b'second version' in resp.data
    assert b'first version' not in resp.data


def test_public_page_unknown_token_404(client):
    anon = client.application.test_client()
    assert anon.get('/n/does-not-exist').status_code == 404


# ===== revocation =====

def test_stop_sharing_revokes_link(client):
    login(client)
    note = _create_note(client, content_markdown='secret')
    token = _share(client, note['id']).get_json()['token']

    anon = client.application.test_client()
    assert anon.get(f'/n/{token}').status_code == 200

    resp = client.delete(f'/api/notes/{note["id"]}/share')
    assert resp.status_code == 204
    assert anon.get(f'/n/{token}').status_code == 404
    assert NoteShare.query.filter_by(note_id=note['id']).first() is None
    assert client.get(f'/api/notes/{note["id"]}').get_json()['public_share_token'] is None
    assert ChangeLog.query.filter_by(
        entity_type='note', entity_id=note['id'], action='unshare').first() is not None


def test_stop_sharing_is_idempotent(client):
    login(client)
    note = _create_note(client, content_markdown='x')
    # No share yet — DELETE still succeeds.
    assert client.delete(f'/api/notes/{note["id"]}/share').status_code == 204


def test_deleting_note_drops_its_share(client):
    login(client)
    note = _create_note(client, content_markdown='bye')
    token = _share(client, note['id']).get_json()['token']
    client.delete(f'/api/notes/{note["id"]}')
    assert NoteShare.query.filter_by(token=token).first() is None
    anon = client.application.test_client()
    assert anon.get(f'/n/{token}').status_code == 404


# ===== auth on the management routes =====

def test_share_routes_require_auth(client):
    # No login(): the create/revoke routes are gated, only the /n/<token> page is public.
    note = Note(space_id=1, content_markdown='x')
    db.session.add(note)
    db.session.commit()
    assert client.post(f'/api/notes/{note.id}/share').status_code == 401
    assert client.delete(f'/api/notes/{note.id}/share').status_code == 401
