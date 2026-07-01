"""
Test harness bootstrap for the simpler-smart-calendar app.

CRITICAL IMPORT ORDER
---------------------
`src/app.py` runs `db.create_all()` + default-space seeding at IMPORT TIME
(module-level `with app.app_context(): ...`). If the prod DB URI
(`sqlite:///tasks.db` -> `instance/tasks.db`) is in place when `app` is
imported, the import will create/seed the production database.

To avoid touching prod state, we Redirect `config.Config.SQLALCHEMY_DATABASE_URI`
to an in-memory SQLite *before* importing `app`, and pin a `StaticPool` so the
single in-memory connection is shared across the whole test session (otherwise
each new connection in `:memory:` mode sees an empty DB and `db.create_all()`
would not persist for the route handlers).

Per-test isolation: the `app` fixture runs `db.drop_all()` + `db.create_all()` +
re-seeds the default spaces inside an app context for every test, so tests do
not leak rows into one another. The import-time create_all already happened, but
the per-test reset guarantees a clean slate regardless of what earlier tests
did.
"""

import sys
import os

# Make `src/` importable so `from app import app`, `from ai_parser import ...`
# resolve the same way they do at runtime under `PYTHONPATH=/app` (Dockerfile).
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import config
from sqlalchemy.pool import StaticPool

# REDIRECT prod DB -> in-memory BEFORE importing `app` (which calls
# db.create_all() + seeding at import time).
config.Config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
# Keep one in-memory connection alive for the whole session.
config.Config.SQLALCHEMY_ENGINE_OPTIONS = {"poolclass": StaticPool}
# Tests should not need real AI credentials.
os.environ.setdefault("AI_API_KEY", "stub-key-not-used-in-tests")
os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ.setdefault("SECRET_KEY", "test-secret")

# Import the Flask app under an ALIASED name (`flask_app`). The pytest fixture
# below is named `app` (the pytest-flask convention); if we imported `app` here
# the fixture definition would shadow the Flask app object and the fixture body
# would call `app.app_context()` on the fixture-definition object → AttributeError.
from app import app as flask_app, db  # noqa: E402  (import after config redirect)
from ai_parser import AIProvider, parse_task_with_ai, get_ai_provider  # noqa: E402
import ai_parser  # noqa: E402  (module handle for monkeypatching)
from models import Space, Note  # noqa: E402
# Seeding is shared with the app factory (src/seeding.py) — no duplication.
from seeding import DEFAULT_SPACES, seed_default_spaces as _seed_default_spaces  # noqa: E402


class StubAIProvider(AIProvider):
    """
    Deterministic AI provider for tests.

    Returns canned responses for BOTH `parse_task` (this issue, 000) and
    `cleanify` (landed here ahead of time — issue 002 needs the stub to already
    have a `cleanify` returning a canned markdown string).
    """

    PARSED_TASKS_CANNED = [
        {
            "title": "buy milk",
            "priority": 5,
            "space_id": None,
            "deadline": None,
            "estimated_duration": 60,
            "description": "buy milk",
        }
    ]

    CLEANIFIED_CANNED = "cleaned"

    def __init__(self, api_key="stub", base_url=None, model=None):
        super().__init__(api_key=api_key, base_url=base_url, model=model)

    def parse_task(self, text, system_prompt):
        return list(self.PARSED_TASKS_CANNED)

    def cleanify(self, note_text, system_prompt):
        return self.CLEANIFIED_CANNED


import pytest  # noqa: E402


@pytest.fixture
def app():
    """Flask app with a freshly reset in-memory DB per test.

    Uses the module-level `flask_app` (imported above under an alias to avoid
    the fixture name shadowing the Flask app object). Per-test: drop_all +
    create_all + re-seed default spaces, inside a pushed app context that
    stays live for the duration of the test (so `client` requests and
    in-test model queries share the same in-memory connection via StaticPool).
    """
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        _seed_default_spaces()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client):
    """Bypass `login_required` by setting the session flag it checks.

    `src/app.py`'s `login_required` decorator returns 401 unless
    `session['authenticated']` is truthy. Call this at the top of any test
    that hits a protected route.
    """
    with client.session_transaction() as sess:
        sess['authenticated'] = True


@pytest.fixture
def sample_note(app):
    """A Note owned by the seeded `work` Space (space_id=1, which has a
    non-empty description). For cleanify/promote route tests (issues 004/005).
    """
    note = Note(space_id=1, title='sample', content_markdown='original messy content')
    db.session.add(note)
    db.session.commit()
    return note


@pytest.fixture
def stub_ai_provider(monkeypatch):
    """
    Patch `ai_parser.get_ai_provider` to return a StubAIProvider instance.

    This is the correct seam: `parse_task_with_ai` calls `get_ai_provider()`
    at call time (not import time), so patching the module global is enough.
    """
    stub = StubAIProvider()
    monkeypatch.setattr(ai_parser, "get_ai_provider", lambda: stub)
    return stub


class StubAIProviderRaising(StubAIProvider):
    """Stub whose `cleanify` raises, to exercise graceful degradation."""

    def cleanify(self, note_text, system_prompt):
        raise Exception("boom")


@pytest.fixture
def stub_ai_provider_raising(monkeypatch):
    """
    Patch `ai_parser.get_ai_provider` to return a stub whose `cleanify` raises.

    Used by `cleanify_note_with_ai`'s graceful-degradation test (issue 002).
    Reused by issue 004's cleanify route test for the AI-unreachable case.
    """
    stub = StubAIProviderRaising()
    monkeypatch.setattr(ai_parser, "get_ai_provider", lambda: stub)
    return stub
