"""Mail module route tests — PrePRD 000 decision G.

IMAP is patched at the route seam (routes.mailboxes.fetch_messages /
fetch_message_body); the AI provider uses the shared stub. Security
assertions: passwords encrypted at rest, never returned by any endpoint.
"""

import pytest

import routes.mailboxes as mailboxes_module
from conftest import login
from crypto_utils import decrypt_secret, encrypt_secret
from models import db, ChangeLog, Mailbox

CANNED_MESSAGES = [
    {'uid': '101', 'subject': 'Quarterly report due',
     'from': 'boss@example.com', 'date': 'Tue, 30 Jun 2026 10:00:00 +0200',
     'snippet': 'Please send the quarterly report by Friday', 'unread': True},
    {'uid': '100', 'subject': 'Lunch?',
     'from': 'friend@example.com', 'date': 'Mon, 29 Jun 2026 12:00:00 +0200',
     'snippet': 'Want to grab lunch tomorrow?', 'unread': False},
]


def make_mailbox(client, **overrides):
    body = {
        'label': 'Work inbox',
        'host': 'imap.example.com',
        'port': 993,
        'username': 'user@example.com',
        'password': 'super-secret',
        'space_id': 1,
        **overrides,
    }
    resp = client.post('/api/mailboxes', json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


@pytest.fixture
def stub_imap(monkeypatch):
    """Patch the IMAP seam with canned messages."""
    calls = {}

    def fake_fetch_messages(host, port, username, password, use_ssl=True, limit=30):
        calls['fetch'] = {'host': host, 'username': username, 'password': password}
        return list(CANNED_MESSAGES)

    def fake_fetch_message_body(host, port, username, password, uid, use_ssl=True):
        calls['body'] = {'uid': uid, 'password': password}
        for msg in CANNED_MESSAGES:
            if msg['uid'] == uid:
                return {**msg, 'body': 'Full body: ' + msg['snippet']}
        return None

    monkeypatch.setattr(mailboxes_module, 'fetch_messages', fake_fetch_messages)
    monkeypatch.setattr(mailboxes_module, 'fetch_message_body', fake_fetch_message_body)
    return calls


def test_crypto_roundtrip():
    token = encrypt_secret('hunter2', 'a-secret-key')
    assert token != 'hunter2'
    assert decrypt_secret(token, 'a-secret-key') == 'hunter2'


def test_create_mailbox_encrypts_password_and_never_returns_it(client, app):
    login(client)
    body = make_mailbox(client)

    assert 'password' not in body
    assert 'password_encrypted' not in body
    assert body['has_password'] is True
    assert body['space'] == 'work'

    row = db.session.get(Mailbox, body['id'])
    assert 'super-secret' not in row.password_encrypted
    key = app.config['SECRET_KEY']
    assert decrypt_secret(row.password_encrypted, key) == 'super-secret'

    # GET list is equally silent about the password
    listed = client.get('/api/mailboxes').get_json()
    assert listed[0]['has_password'] is True
    assert 'password' not in listed[0] and 'password_encrypted' not in listed[0]

    # Audited
    assert ChangeLog.query.filter_by(entity_type='mailbox', action='create').count() == 1


def test_create_mailbox_requires_credentials(client):
    login(client)
    resp = client.post('/api/mailboxes', json={'label': 'x', 'host': 'h', 'username': 'u'})
    assert resp.status_code == 400


def test_update_relinks_space_and_keeps_password_when_absent(client, app):
    login(client)
    body = make_mailbox(client)
    resp = client.put(f"/api/mailboxes/{body['id']}", json={'space_id': 2})
    assert resp.status_code == 200
    assert resp.get_json()['space_id'] == 2

    row = db.session.get(Mailbox, body['id'])
    assert decrypt_secret(row.password_encrypted, app.config['SECRET_KEY']) == 'super-secret'


def test_delete_mailbox_is_audited(client):
    login(client)
    body = make_mailbox(client)
    resp = client.delete(f"/api/mailboxes/{body['id']}")
    assert resp.status_code == 200
    assert db.session.get(Mailbox, body['id']) is None
    assert ChangeLog.query.filter_by(
        entity_type='mailbox', entity_id=body['id'], action='delete').count() == 1


def test_messages_live_fetch_returns_canned_dtos(client, stub_imap):
    login(client)
    body = make_mailbox(client)
    resp = client.get(f"/api/mailboxes/{body['id']}/messages")
    assert resp.status_code == 200
    messages = resp.get_json()
    assert [m['uid'] for m in messages] == ['101', '100']
    # The IMAP call received the DECRYPTED password (in memory only)
    assert stub_imap['fetch']['password'] == 'super-secret'


def test_add_task_returns_draft_tagged_with_mailbox_space_and_persists_nothing(
        client, stub_imap, stub_ai_provider):
    login(client)
    body = make_mailbox(client, space_id=2)

    resp = client.post(f"/api/mailboxes/{body['id']}/messages/101/add-task")
    assert resp.status_code == 200
    drafts = resp.get_json()
    assert isinstance(drafts, list) and len(drafts) == 1
    # Stub AI returns space_id=None -> pre-tagged with the mailbox's space
    assert drafts[0]['space_id'] == 2

    from models import Task
    assert Task.query.count() == 0


def test_add_task_unknown_uid_is_404(client, stub_imap, stub_ai_provider):
    login(client)
    body = make_mailbox(client)
    resp = client.post(f"/api/mailboxes/{body['id']}/messages/999/add-task")
    assert resp.status_code == 404


def test_messages_imap_failure_maps_to_502(client, monkeypatch):
    login(client)
    body = make_mailbox(client)

    def boom(*args, **kwargs):
        raise OSError('connection refused')

    monkeypatch.setattr(mailboxes_module, 'fetch_messages', boom)
    resp = client.get(f"/api/mailboxes/{body['id']}/messages")
    assert resp.status_code == 502
