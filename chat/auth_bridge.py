"""Bridge Simpler's Flask session to Chainlit's header auth.

The assistant is mounted same-origin (asgi.py), so the browser sends the
Flask `session` cookie with every request to /assistant. Chainlit calls our
`header_auth_callback` with the request headers; we verify the cookie's
signature with the SAME SECRET_KEY Flask signs it with and accept when the
session carries `authenticated: True` (set by /login in routes/pages.py).
One login gates everything — no second login screen inside the chat.

Verification reuses Flask's own SecureCookieSessionInterface (via a throwaway
Flask app carrying only the secret key) so the key-derivation/salt/digest
details can never drift from what Flask actually does.
"""

from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from werkzeug.http import parse_cookie

_serializer = None
_serializer_key = None


def _get_serializer(secret_key: str):
    global _serializer, _serializer_key
    if _serializer is None or _serializer_key != secret_key:
        shim = Flask('simpler-session-shim')
        shim.secret_key = secret_key
        _serializer = SecureCookieSessionInterface().get_signing_serializer(shim)
        _serializer_key = secret_key
    return _serializer


def session_from_cookie_header(cookie_header, secret_key: str):
    """Decode + verify the Flask session from a raw Cookie header value.

    Returns the session dict, or None when absent/invalid/tampered.
    """
    if not cookie_header or not secret_key:
        return None
    raw = parse_cookie(cookie_header).get('session')
    if not raw:
        return None
    serializer = _get_serializer(secret_key)
    if serializer is None:
        return None
    try:
        return serializer.loads(raw)
    except Exception:
        return None


def is_authenticated(cookie_header, secret_key: str) -> bool:
    """True when the Cookie header carries a validly-signed, logged-in
    Simpler session."""
    session = session_from_cookie_header(cookie_header, secret_key)
    return bool(session and session.get('authenticated'))
