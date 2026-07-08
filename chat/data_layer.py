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

import sqlite3

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


def ensure_schema(db_path: str):
    """Create the Chainlit history tables if missing (idempotent)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def build_data_layer(db_path: str):
    """Bootstrap the schema and return a ready SQLAlchemyDataLayer."""
    # Imported lazily: this module is used by plain pytest without Chainlit's
    # runtime context.
    from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

    ensure_schema(db_path)
    return SQLAlchemyDataLayer(conninfo=f'sqlite+aiosqlite:///{db_path}')
