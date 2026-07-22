"""chat/data_layer.py — Chainlit chat-history persistence on SQLite.

Exercises the REAL SQLAlchemyDataLayer against our SQLite schema (user +
thread + steps + listing), since the official Chainlit schema is
Postgres-flavored and this project owns the SQLite translation.
"""

import asyncio
import json
import sqlite3
import uuid

import pytest

chainlit = pytest.importorskip('chainlit', reason='chainlit not installed')

from chainlit.types import Pagination, ThreadFilter  # noqa: E402
from chainlit.user import User  # noqa: E402

from chat.data_layer import build_data_layer, ensure_schema  # noqa: E402


def test_ensure_schema_idempotent(tmp_path):
    db_path = str(tmp_path / 'chainlit.db')
    ensure_schema(db_path)
    ensure_schema(db_path)  # second run must be a no-op, not an error

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {'users', 'threads', 'steps', 'elements', 'feedbacks'} <= tables


def test_ensure_schema_adds_autocollapse_to_legacy_steps_table(tmp_path):
    """Regression: an existing chainlit.db created before Chainlit 2.11
    has a `steps` table WITHOUT the `autoCollapse` column the running
    Chainlit now writes in every INSERT. ensure_schema must back-fill it
    (CREATE TABLE IF NOT EXISTS alone cannot evolve an existing table).
    See https://github.com/Chainlit/chainlit/issues/2865."""
    db_path = str(tmp_path / 'chainlit.db')

    # Build a pre-fix DB: steps table matching the old SCHEMA (no
    # autoCollapse), plus the other tables ensure_schema expects to find.
    conn = sqlite3.connect(db_path)
    conn.executescript('''
        CREATE TABLE users (id TEXT PRIMARY KEY);
        CREATE TABLE threads (id TEXT PRIMARY KEY);
        CREATE TABLE steps (
            id TEXT PRIMARY KEY, name TEXT, type TEXT, threadId TEXT,
            parentId TEXT, streaming BOOLEAN, waitForAnswer BOOLEAN,
            isError BOOLEAN, metadata TEXT, tags TEXT, input TEXT,
            output TEXT, createdAt TEXT, command TEXT, start TEXT,
            end TEXT, generation TEXT, showInput TEXT, language TEXT,
            indent INT, defaultOpen BOOLEAN, modes TEXT
        );
        CREATE TABLE elements (id TEXT PRIMARY KEY);
        CREATE TABLE feedbacks (
            id TEXT PRIMARY KEY, forId TEXT, threadId TEXT,
            value INT, comment TEXT
        );
    ''')
    conn.commit()
    conn.close()

    def columns():
        c = sqlite3.connect(db_path)
        cols = [r[1] for r in c.execute('PRAGMA table_info(steps)')]
        c.close()
        return cols

    assert 'autoCollapse' not in columns()  # pre-fix baseline

    ensure_schema(db_path)  # must back-fill, NOT silently no-op
    assert 'autoCollapse' in columns()

    # Back-fill is itself idempotent.
    ensure_schema(db_path)
    ensure_schema(db_path)
    assert 'autoCollapse' in columns()


def test_data_layer_thread_and_step_tags_round_trip_as_lists(tmp_path):
    """Regression: Chainlit's SQLAlchemyDataLayer writes `tags` as a raw
    Python list (Postgres array column). On our SQLite TEXT column that
    raises `InterfaceError: Error binding parameter 5 - probably
    unsupported type` on write, and a JSON string round-trips on read
    instead of a list. SimplerSQLiteDataLayer must serialize lists→JSON on
    write and deserialize JSON→list on every read path.

    See https://github.com/Chainlit/chainlit — upstream serializes
    `metadata` with json.dumps() but not `tags`, an inconsistency that is
    invisible on Postgres (array type) and fatal on SQLite.
    """
    db_path = str(tmp_path / 'chainlit.db')
    layer = build_data_layer(db_path)

    async def scenario():
        user = await layer.create_user(User(identifier='owner'))
        assert user is not None and user.id

        thread_id = str(uuid.uuid4())
        # The exact call that raised InterfaceError before the fix:
        # tags as a Python list, not a JSON string.
        await layer.update_thread(
            thread_id, name='#20 — tags bug', user_id=user.id,
            tags=['qwen3.6-35b-fast'],
        )

        # Stored as JSON TEXT in the DB (not a raw list bind).
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT "tags" FROM threads WHERE "id" = ?', (thread_id,)
        ).fetchone()
        conn.close()
        assert row[0] == '["qwen3.6-35b-fast"]', row[0]
        assert json.loads(row[0]) == ['qwen3.6-35b-fast']

        # create_step with list tags (latent same bug on the steps table).
        create_step = type(layer).create_step.__wrapped__
        step_id = str(uuid.uuid4())
        await create_step(layer, {
            'id': step_id,
            'threadId': thread_id,
            'name': 'owner',
            'type': 'user_message',
            'streaming': False,
            'output': 'hello assistant',
            'tags': ['planning', 'urgent'],
            'createdAt': '2026-07-08T10:00:00Z',
        })

        # Every read path must return tags as a LIST, not a JSON string.
        thread = await layer.get_thread(thread_id)
        assert thread['tags'] == ['qwen3.6-35b-fast']
        assert isinstance(thread['tags'], list)
        assert thread['steps'][0]['tags'] == ['planning', 'urgent']
        assert isinstance(thread['steps'][0]['tags'], list)

        listing = await layer.list_threads(
            Pagination(first=10), ThreadFilter(userId=user.id))
        assert listing.data[0]['tags'] == ['qwen3.6-35b-fast']

        all_threads = await layer.get_all_user_threads(user_id=user.id)
        assert all_threads[0]['tags'] == ['qwen3.6-35b-fast']
        assert all_threads[0]['steps'][0]['tags'] == ['planning', 'urgent']

        step = await layer.get_step(step_id)
        assert step['tags'] == ['planning', 'urgent']

        # Regression: a thread WITHOUT tags still works (the None path).
        bare_id = str(uuid.uuid4())
        await layer.update_thread(bare_id, name='no tags', user_id=user.id)
        bare = await layer.get_thread(bare_id)
        assert bare['tags'] is None

    asyncio.run(scenario())


def test_data_layer_step_modes_round_trip_as_dict(tmp_path):
    """Regression: Chainlit 2.11's mode selector puts a `modes` dict
    ({'model': ..., 'reasoning': ...}) on every user_message step. Upstream
    json.dumps()es only `metadata` and `generation`, so the dict was bound
    verbatim and SQLite refused it:

        sqlite3.ProgrammingError: Error binding parameter 4:
        type 'dict' is not supported

    That raised inside the persistence path, so the chat kept working while
    every user message was silently dropped from the history DB. Same shape
    as the `tags` bug — invisible on Postgres (JSONB), fatal on SQLite.
    """
    db_path = str(tmp_path / 'chainlit.db')
    layer = build_data_layer(db_path)

    async def scenario():
        user = await layer.create_user(User(identifier='owner'))
        thread_id = str(uuid.uuid4())
        await layer.update_thread(thread_id, name='modes bug', user_id=user.id)

        create_step = type(layer).create_step.__wrapped__
        step_id = str(uuid.uuid4())
        # The exact payload shape that raised ProgrammingError.
        await create_step(layer, {
            'id': step_id,
            'threadId': thread_id,
            'name': 'owner',
            'type': 'user_message',
            'streaming': False,
            'output': 'test hello',
            'modes': {'model': 'glm-5.2-short', 'reasoning': 'low'},
            'metadata': {'location': 'http://localhost:53000/assistant/'},
            'createdAt': '2026-07-22T11:26:22.447419Z',
        })

        # Stored as JSON TEXT, not a raw dict bind.
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT "modes" FROM steps WHERE "id" = ?', (step_id,)).fetchone()
        conn.close()
        assert json.loads(row[0]) == {'model': 'glm-5.2-short', 'reasoning': 'low'}

        # The step is actually persisted and readable — the point of the fix
        # is that the message stops vanishing from the history DB.
        step = await layer.get_step(step_id)
        assert step['output'] == 'test hello'

        thread = await layer.get_thread(thread_id)
        assert [s['output'] for s in thread['steps']] == ['test hello']

        # `modes` is write-only in this Chainlit version — its read queries
        # never SELECT the column. _coerce_json_fields covers it anyway, so
        # whenever it DOES come back it must be a dict, never a JSON string.
        for source in (step, thread['steps'][0]):
            assert not isinstance(source.get('modes'), str)

        # A step without modes still works (the missing-key path).
        bare_id = str(uuid.uuid4())
        await create_step(layer, {
            'id': bare_id,
            'threadId': thread_id,
            'name': 'assistant',
            'type': 'assistant_message',
            'streaming': False,
            'output': 'hi',
            'createdAt': '2026-07-22T11:26:23.000000Z',
        })
        assert (await layer.get_step(bare_id))['output'] == 'hi'

    asyncio.run(scenario())


def test_empty_modes_does_not_clobber_stored_modes(tmp_path):
    """Upstream drops empty-dict parameters before building the statement, so
    the column is omitted and the ON CONFLICT UPDATE keeps what is stored.
    Serializing {} to '{}' here would overwrite a real value on the next
    update of the same step id."""
    db_path = str(tmp_path / 'chainlit.db')
    layer = build_data_layer(db_path)

    async def scenario():
        user = await layer.create_user(User(identifier='owner'))
        thread_id = str(uuid.uuid4())
        await layer.update_thread(thread_id, name='t', user_id=user.id)

        create_step = type(layer).create_step.__wrapped__
        step_id = str(uuid.uuid4())
        base = {
            'id': step_id, 'threadId': thread_id, 'name': 'owner',
            'type': 'user_message', 'streaming': False,
            'createdAt': '2026-07-22T11:26:22.447419Z',
        }
        await create_step(layer, dict(base, output='v1',
                                      modes={'model': 'glm-5.2-short'}))
        # Same step re-upserted with an empty modes dict.
        await create_step(layer, dict(base, output='v2', modes={}))

        assert (await layer.get_step(step_id))['output'] == 'v2'

        # Read the column directly — upstream's SELECTs do not include `modes`.
        conn = sqlite3.connect(db_path)
        stored = conn.execute(
            'SELECT "modes" FROM steps WHERE "id" = ?', (step_id,)).fetchone()[0]
        conn.close()
        assert json.loads(stored) == {'model': 'glm-5.2-short'}

    asyncio.run(scenario())


def test_ensure_schema_adds_modes_to_legacy_steps_table(tmp_path):
    """A chainlit.db created before `modes` joined SCHEMA has no such column;
    CREATE TABLE IF NOT EXISTS cannot evolve it, so ensure_schema must."""
    db_path = str(tmp_path / 'chainlit.db')
    conn = sqlite3.connect(db_path)
    conn.executescript('''
        CREATE TABLE users (id TEXT PRIMARY KEY);
        CREATE TABLE threads (id TEXT PRIMARY KEY);
        CREATE TABLE steps (
            id TEXT PRIMARY KEY, name TEXT, type TEXT, threadId TEXT,
            streaming BOOLEAN, metadata TEXT, tags TEXT, output TEXT,
            createdAt TEXT
        );
        CREATE TABLE elements (id TEXT PRIMARY KEY);
        CREATE TABLE feedbacks (id TEXT PRIMARY KEY);
    ''')
    conn.commit()
    conn.close()

    def columns():
        c = sqlite3.connect(db_path)
        cols = [r[1] for r in c.execute('PRAGMA table_info(steps)')]
        c.close()
        return cols

    assert 'modes' not in columns()  # pre-fix baseline
    ensure_schema(db_path)
    assert 'modes' in columns()
    ensure_schema(db_path)  # idempotent
    assert 'modes' in columns()


def test_data_layer_full_thread_lifecycle(tmp_path):
    db_path = str(tmp_path / 'chainlit.db')
    layer = build_data_layer(db_path)

    async def scenario():
        user = await layer.create_user(User(identifier='owner'))
        assert user is not None and user.id

        thread_id = str(uuid.uuid4())
        await layer.update_thread(thread_id, name='test thread', user_id=user.id)

        # create_step is wrapped by @queue_until_user_message, which needs a
        # live Chainlit websocket context; call the undecorated method — the
        # persistence logic under test is identical.
        create_step = type(layer).create_step.__wrapped__
        step_id = str(uuid.uuid4())
        await create_step(layer, {
            'id': step_id,
            'threadId': thread_id,
            'name': 'owner',
            'type': 'user_message',
            'streaming': False,
            'output': 'hello assistant',
            'createdAt': '2026-07-08T10:00:00Z',
        })

        thread = await layer.get_thread(thread_id)
        assert thread is not None
        assert thread['name'] == 'test thread'
        assert any(step['output'] == 'hello assistant' for step in thread['steps'])

        listing = await layer.list_threads(
            Pagination(first=10), ThreadFilter(userId=user.id))
        assert [t['id'] for t in listing.data] == [thread_id]

        author = await layer.get_thread_author(thread_id)
        assert author == 'owner'

        await layer.delete_thread(thread_id)
        assert await layer.get_thread(thread_id) is None

    asyncio.run(scenario())
