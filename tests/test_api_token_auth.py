"""Bearer-token auth mode (PRD 002 §3.2) + agent actor attribution (§3.5).

`API_TOKEN` unset ⇒ behavior byte-identical to before: only the session
cookie authenticates. Set ⇒ `Authorization: Bearer <API_TOKEN>` is accepted
on every @login_required route, and mutations made that way are audited with
actor='agent' (explicit route actors like the parse path's 'ai' still win).
"""

import json

from conftest import login
from models import ChangeLog

TOKEN = 'test-api-token-123'


def bearer(token=TOKEN):
    return {'Authorization': f'Bearer {token}'}


def test_valid_token_grants_access(app, client):
    app.config['API_TOKEN'] = TOKEN
    resp = client.get('/api/tasks', headers=bearer())
    assert resp.status_code == 200


def test_wrong_token_401(app, client):
    app.config['API_TOKEN'] = TOKEN
    resp = client.get('/api/tasks', headers=bearer('wrong-token'))
    assert resp.status_code == 401


def test_malformed_authorization_header_401(app, client):
    app.config['API_TOKEN'] = TOKEN
    resp = client.get('/api/tasks', headers={'Authorization': TOKEN})
    assert resp.status_code == 401
    resp = client.get('/api/tasks', headers={'Authorization': f'Basic {TOKEN}'})
    assert resp.status_code == 401


def test_no_token_still_cookie_gated(app, client):
    app.config['API_TOKEN'] = TOKEN
    assert client.get('/api/tasks').status_code == 401
    login(client)
    assert client.get('/api/tasks').status_code == 200


def test_feature_off_rejects_bearer(app, client):
    app.config['API_TOKEN'] = None
    resp = client.get('/api/tasks', headers=bearer())
    assert resp.status_code == 401
    # Empty string counts as unset too (never compare against '').
    app.config['API_TOKEN'] = ''
    resp = client.get('/api/tasks', headers={'Authorization': 'Bearer '})
    assert resp.status_code == 401


def test_bearer_mutation_audited_as_agent(app, client):
    app.config['API_TOKEN'] = TOKEN
    resp = client.post('/api/tasks', json={'title': 'agent-made'}, headers=bearer())
    assert resp.status_code == 201
    task_id = resp.get_json()['id']

    log = ChangeLog.query.filter_by(entity_type='task', entity_id=task_id,
                                    action='create').one()
    assert log.actor == 'agent'
    assert json.loads(log.new_value)['title'] == 'agent-made'


def test_session_mutation_still_audited_as_user(app, client):
    app.config['API_TOKEN'] = TOKEN
    login(client)
    resp = client.post('/api/tasks', json={'title': 'user-made'})
    assert resp.status_code == 201
    task_id = resp.get_json()['id']

    log = ChangeLog.query.filter_by(entity_type='task', entity_id=task_id,
                                    action='create').one()
    assert log.actor == 'user'


def test_bearer_ai_parse_keeps_explicit_ai_actor(app, client, stub_ai_provider):
    app.config['API_TOKEN'] = TOKEN
    resp = client.post('/api/tasks/parse', json={'text': 'buy milk'}, headers=bearer())
    assert resp.status_code == 201
    task_id = resp.get_json()['id']

    log = ChangeLog.query.filter_by(entity_type='task', entity_id=task_id,
                                    action='create').one()
    assert log.actor == 'ai'
