"""chat/data_layer.py — Chainlit chat-history persistence on SQLite.

Exercises the REAL SQLAlchemyDataLayer against our SQLite schema (user +
thread + steps + listing), since the official Chainlit schema is
Postgres-flavored and this project owns the SQLite translation.
"""

import asyncio
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
