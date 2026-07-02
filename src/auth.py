"""Authentication seam: the single shared-password session gate.

There is no user table — one `APP_PASSWORD` gates everything (see
doc/PROJECT_DESCRIPTION.md). Every API blueprint imports `login_required`
from here.
"""

from functools import wraps

from flask import jsonify, session


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function
