"""Chat history persistence: Chainlit's SQLAlchemy data layer on SQLite.

Chainlit's SQLAlchemyDataLayer issues raw SQL against five tables but does
not create them; the official schema is Postgres-flavored, so this module
owns the SQLite translation (TEXT ids instead of UUID, TEXT for JSON, no
array type) and bootstraps it idempotently before the layer is handed to
Chainlit. The DB lives next to the app's own SQLite file in instance/.

No storage provider is configured: element payloads (file uploads) are not
persisted across thread reloads, which is fine for a single-user assistant —
uploaded file *content* is consumed into the conversation at message time.
"""

import json
import sqlite3

from chainlit.data import queue_until_user_message
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT,
    "metadata" TEXT,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "parentId" TEXT,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    "autoCollapse" BOOLEAN,
    "modes" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" TEXT,
    "mime" TEXT,
    "props" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""


# Columns Chainlit's SQLAlchemyDataLayer writes but earlier SCHEMA versions
# did not create. Each entry is added to an existing `steps` table via
# ALTER TABLE when missing (CREATE TABLE IF NOT EXISTS cannot evolve an
# already-present table). Mirrors the upstream migration gaps documented at
# https://github.com/Chainlit/chainlit/issues/2865 (autoCollapse landed in
# 2.10.0 / stabilized in 2.11.0 with no schema-migration note).
STEPS_ADDITIVE_COLUMNS = [
    ("autoCollapse", "BOOLEAN"),
    # 2.11's mode selector (model + reasoning per message). Present in SCHEMA
    # above, so only DBs created before it landed need the ALTER.
    ("modes", "TEXT"),
]


def ensure_schema(db_path: str):
    """Create the Chainlit history tables if missing and evolve an existing
    `steps` table with any columns later Chainlit versions started writing
    (idempotent; safe on fresh and pre-existing databases)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so a
        # DB created by an older SCHEMA will be missing columns the running
        # Chainlit now emits in every INSERT. Add them here.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(steps)")}
        for col, coltype in STEPS_ADDITIVE_COLUMNS:
            if col not in existing:
                conn.execute(
                    f'ALTER TABLE steps ADD COLUMN "{col}" {coltype}'
                )
        _backfill_null_created_at(conn)
        conn.commit()
    finally:
        conn.close()


def _backfill_null_created_at(conn):
    """Heal steps written with createdAt=NULL.

    A streamed assistant answer finalized with `Message.update()` (the old
    UIHooks path) persisted with no createdAt. On resume Chainlit orders steps
    `createdAt ASC` — NULLs sort first, ahead of the answer's parent
    `on_message` run step — and the frontend tree-builder drops any step whose
    parent isn't placed yet, so those answers vanish on reload. Give each
    NULL-createdAt row the timestamp of the nearest preceding step in the same
    thread (rowid order = insertion order = chronological), which sorts it back
    into place. Idempotent: only NULL rows are touched, and a row with no
    earlier timestamped sibling is left alone.
    """
    conn.execute(
        '''
        UPDATE steps SET "createdAt" = (
            SELECT s2."createdAt" FROM steps s2
            WHERE s2."threadId" = steps."threadId"
              AND s2.rowid < steps.rowid
              AND s2."createdAt" IS NOT NULL
            ORDER BY s2.rowid DESC LIMIT 1
        )
        WHERE "createdAt" IS NULL
          AND EXISTS (
            SELECT 1 FROM steps s3
            WHERE s3."threadId" = steps."threadId"
              AND s3.rowid < steps.rowid
              AND s3."createdAt" IS NOT NULL
          )
        '''
    )


# Columns that are native structured types on Postgres (array / JSONB) but
# plain TEXT on SQLite, and that upstream does NOT serialize itself. Upstream
# json.dumps()es only `metadata` and `generation` (sql_alchemy.create_step);
# everything else is bound verbatim, and aiosqlite refuses to bind a Python
# list/dict ("type 'dict' is not supported"). Each entry here is JSON-encoded
# on write and decoded on read.
#
#   tags   — list, threads + steps
#   modes  — dict, steps (chat profile modes: model + reasoning). Added by
#            Chainlit 2.11's mode selector; hit us as a hard write failure that
#            silently dropped every user_message from the history DB.
#
# When a Chainlit upgrade adds another structured step field, it belongs here.
JSON_TEXT_FIELDS = ('tags', 'modes')


def _coerce_json_fields(obj):
    """Deserialize the SQLite TEXT columns in `JSON_TEXT_FIELDS` back to the
    list/dict the Chainlit dict API expects.

    Chainlit's SQLAlchemyDataLayer is written for Postgres, where these are
    native array/JSONB columns — written as a Python list/dict, read back as
    one. On SQLite we store them as JSON TEXT (see
    `SimplerSQLiteDataLayer.update_thread`/`create_step`), so we must undo
    that on every read path that returns a ThreadDict/StepDict to Chainlit
    or the UI. Safe on None, missing keys, or already-decoded values.
    """
    if not obj or not isinstance(obj, dict):
        return obj
    for field in JSON_TEXT_FIELDS:
        raw = obj.get(field)
        if isinstance(raw, str):
            try:
                obj[field] = json.loads(raw)
            except json.JSONDecodeError:
                pass  # leave untouched if it isn't JSON we wrote
    return obj


class SimplerSQLiteDataLayer(SQLAlchemyDataLayer):
    """SQLite-aware shim over Chainlit's Postgres-flavored SQLAlchemyDataLayer.

    Two translation problems exist because upstream targets Postgres:

    1. Structured columns (`tags` on threads + steps, `modes` on steps) are
       native array/JSONB on Postgres but TEXT on SQLite; upstream binds the
       raw Python list/dict verbatim, which aiosqlite refuses
       (`InterfaceError: unsupported type` / `ProgrammingError: type 'dict'
       is not supported`). Upstream only json.dumps()es `metadata` and
       `generation` — see `JSON_TEXT_FIELDS`.
    2. Reading that TEXT back yields a JSON string instead of the list/dict
       the Chainlit dict API (and the UI) expects.

    This subclass fixes both at the object/parameter seam — JSON-serialize the
    `JSON_TEXT_FIELDS` before delegating the write, JSON-deserialize them after
    delegating the read — so all actual SQL stays upstream and we are immune
    to method-body drift in future Chainlit versions. When the chat DB moves
    to Postgres this whole class goes away.

    Failure mode when a field is missing from `JSON_TEXT_FIELDS`: the write
    raises inside Chainlit's persistence path, the message never lands in the
    history DB, and the chat keeps working — so the loss is silent until a
    thread is resumed and turns out to be empty.
    """

    async def update_thread(self, thread_id, name=None, user_id=None,
                            metadata=None, tags=None):
        if isinstance(tags, list):
            tags = json.dumps(tags)
        return await super().update_thread(
            thread_id, name=name, user_id=user_id, metadata=metadata,
            tags=tags,
        )

    @queue_until_user_message()
    async def create_step(self, step_dict):
        # Re-apply the queue decorator so external callers keep the same
        # until-user-message persistence deferral upstream relies on (and
        # so `create_step.__wrapped__`, used by tests, resolves to this body).
        # We then delegate to the upstream UNWRAPPED body to avoid
        # double-queueing → SQLAlchemyDataLayer.create_step.__wrapped__.
        prepared = dict(step_dict)
        for field in JSON_TEXT_FIELDS:
            value = prepared.get(field)
            # An EMPTY dict is left alone on purpose: upstream drops empty-dict
            # parameters before building the statement, so the column is
            # omitted and the ON CONFLICT UPDATE keeps whatever is already
            # stored. Serializing it to '{}' here would clobber that.
            if isinstance(value, list) or (isinstance(value, dict) and value):
                prepared[field] = json.dumps(value)
        return await SQLAlchemyDataLayer.create_step.__wrapped__(
            self, prepared)

    async def get_thread(self, thread_id):
        thread = await super().get_thread(thread_id)
        if thread is not None:
            _coerce_json_fields(thread)
            for step in thread.get('steps', []) or []:
                _coerce_json_fields(step)
        return thread

    async def list_threads(self, pagination, filters):
        result = await super().list_threads(pagination, filters)
        for thread in (result.data or []):
            _coerce_json_fields(thread)
            for step in thread.get('steps', []) or []:
                _coerce_json_fields(step)
        return result

    async def get_all_user_threads(self, user_id=None, thread_id=None):
        threads = await super().get_all_user_threads(
            user_id=user_id, thread_id=thread_id)
        for thread in threads or []:
            _coerce_json_fields(thread)
            for step in thread.get('steps', []) or []:
                _coerce_json_fields(step)
        return threads

    async def get_step(self, step_id):
        step = await super().get_step(step_id)
        return _coerce_json_fields(step) if step is not None else step

    async def get_favorite_steps(self, user_id):
        steps = await super().get_favorite_steps(user_id)
        for step in steps or []:
            _coerce_json_fields(step)
        return steps


def build_data_layer(db_path: str):
    """Bootstrap the schema and return a ready data layer for Chainlit."""
    ensure_schema(db_path)
    return SimplerSQLiteDataLayer(conninfo=f'sqlite+aiosqlite:///{db_path}')
