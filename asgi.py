"""One server, one origin: FastAPI umbrella mounting Chainlit + Flask.

    uvicorn asgi:app --host 0.0.0.0 --port 53000

Routing:
    /assistant/*   the Chainlit assistant (native ASGI: websockets stream)
    /*             the existing Flask app (WSGI, unchanged), via a2wsgi

This replaces the former Hermes reverse-proxy approach: the chat UI is a
first-party app in the same process, so there is no sidecar UI container, no
proxy, and auth is bridged by signature (chat/auth_bridge.py reads the Flask
session cookie) rather than by forwarding.

`python src/app.py` still runs the Flask app alone (no Assistant tab) for
quick Flask-only development; this module is the canonical entrypoint.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'src')
for path in (ROOT, SRC):
    if path not in sys.path:
        sys.path.insert(0, path)

# Tell the Flask side the assistant is mounted (shows the Assistant tab) —
# must be set before `config.Config` is evaluated on import.
os.environ['SIMPLER_ASSISTANT_MOUNTED'] = '1'

from chat import settings  # noqa: E402

settings.ensure_chainlit_env()  # CHAINLIT_APP_ROOT + auth secret, pre-import

from a2wsgi import WSGIMiddleware  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from chainlit.utils import mount_chainlit  # noqa: E402

from app import app as flask_app  # noqa: E402  (src/app.py)

app = FastAPI(title='Simpler')

mount_chainlit(
    app=app,
    target=os.path.join(ROOT, 'chat', 'chainlit_app.py'),
    path='/assistant',
)

# Everything else is the Flask app, byte-identical to before.
app.mount('/', WSGIMiddleware(flask_app))


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=53000)
