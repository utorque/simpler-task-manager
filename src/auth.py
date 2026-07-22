"""Authentication seam: session cookie OR machine bearer token.

There is no user table — one `APP_PASSWORD` gates the browser session (see
doc/PROJECT_DESCRIPTION.md), and one optional `API_TOKEN` (env var; unset =
feature off, behavior identical to session-only) gates non-interactive
machine clients such as the `mcp_server/` sidecar. Every API blueprint
imports `login_required` from here.
"""

import hmac
from functools import wraps

from flask import current_app, g, jsonify, request, session


def _bearer_token_valid():
    """True when the request carries `Authorization: Bearer <API_TOKEN>`.

    Always False when API_TOKEN is unset/empty (feature off). Constant-time
    compare — the token is a password-equivalent credential.
    """
    expected = current_app.config.get('API_TOKEN')
    if not expected:
        return False
    header = request.headers.get('Authorization', '')
    scheme, _, presented = header.partition(' ')
    if scheme != 'Bearer' or not presented:
        return False
    return hmac.compare_digest(presented.strip(), expected)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('authenticated'):
            return f(*args, **kwargs)
        if _bearer_token_valid():
            # Machine client (MCP sidecar / embedded assistant). audit.record_change
            # picks this up as the default actor so agent mutations are
            # attributable in the ChangeLog; routes that pass an explicit
            # actor (the AI parse paths' 'ai') keep it.
            g.actor = 'agent'
            return f(*args, **kwargs)
        return jsonify({'error': 'Authentication required'}), 401
    return decorated_function
