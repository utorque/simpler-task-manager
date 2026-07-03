"""GET /api/notes with repeated space_id params (Ctrl+click multi-space view).

?space_id=1&space_id=2 returns the union of those spaces' notes; a single
space_id keeps its old meaning; no space_id returns everything.
"""

from conftest import login
from models import db, Note


def _seed_notes(app):
    # Seeded default spaces have ids 1..n; use the first three.
    notes = [
        Note(space_id=1, title='n1', content_markdown='one'),
        Note(space_id=2, title='n2', content_markdown='two'),
        Note(space_id=3, title='n3', content_markdown='three'),
    ]
    db.session.add_all(notes)
    db.session.commit()
    return notes


def test_multiple_space_ids_return_the_union(client, app):
    login(client)
    _seed_notes(app)

    resp = client.get('/api/notes?space_id=1&space_id=3')
    assert resp.status_code == 200
    assert sorted(n['space_id'] for n in resp.get_json()) == [1, 3]


def test_single_space_id_still_filters(client, app):
    login(client)
    _seed_notes(app)

    resp = client.get('/api/notes?space_id=2')
    assert [n['space_id'] for n in resp.get_json()] == [2]


def test_no_space_id_returns_all_notes(client, app):
    login(client)
    _seed_notes(app)

    resp = client.get('/api/notes')
    assert len(resp.get_json()) == 3
