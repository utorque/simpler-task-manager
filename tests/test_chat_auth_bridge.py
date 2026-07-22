"""chat/auth_bridge.py — Chainlit auth from the Flask session cookie.

Cookies are produced by the REAL Flask app (test client) so the bridge is
verified against exactly what Flask signs, not a reimplementation.
"""

from chat.auth_bridge import is_authenticated, session_from_cookie_header
from conftest import login


def _session_cookie_header(client) -> str:
    cookie = client.get_cookie('session')
    assert cookie is not None, 'expected the test client to hold a session cookie'
    return f'session={cookie.value}'


def test_authenticated_session_accepted(client, app):
    login(client)
    header = _session_cookie_header(client)
    assert is_authenticated(header, app.secret_key)


def test_logged_out_session_rejected(client, app):
    # A validly signed session WITHOUT the authenticated flag.
    with client.session_transaction() as sess:
        sess['something_else'] = True
    header = _session_cookie_header(client)
    assert session_from_cookie_header(header, app.secret_key) is not None
    assert not is_authenticated(header, app.secret_key)


def test_tampered_cookie_rejected(client, app):
    login(client)
    cookie = client.get_cookie('session')
    tampered = f'session={cookie.value[:-4]}XXXX'
    assert session_from_cookie_header(tampered, app.secret_key) is None
    assert not is_authenticated(tampered, app.secret_key)


def test_wrong_secret_rejected(client, app):
    login(client)
    header = _session_cookie_header(client)
    assert not is_authenticated(header, 'a-completely-different-secret')


def test_missing_cookie_rejected(app):
    assert not is_authenticated(None, app.secret_key)
    assert not is_authenticated('', app.secret_key)
    assert not is_authenticated('other=1', app.secret_key)
