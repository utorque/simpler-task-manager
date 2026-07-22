#!/usr/bin/env python3
"""migrate_db.py — additive-only schema reconciler for the prod SQLite DB.

Compares the expected schema (SCHEMA below, mirroring `src/models.py`) against
the actual database file and applies the *additive* diff:

  1. CREATE missing tables + indexes (e.g. `subtasks` landing on a DB that
     predates it).
  2. ALTER TABLE ADD COLUMN for columns on the model but absent in the DB
     (e.g. `tasks.status` on a DB that predates the kanban workflow).
  3. DATA FIXUPS: idempotent UPDATEs backfilling new/canonical columns from
     legacy ones. Each only touches rows where the target is still unset, so
     re-running never overwrites user data.

It NEVER drops tables, columns, or data, and is idempotent — a second run is a
no-op. Stdlib-only (`sqlite3` + `shutil`), so it can be copied to the server
and run without the app's dependencies.

Why a table-driven SCHEMA instead of importing `db.metadata`: keeping it
dependency-free is what makes it copyable to a server that has no venv. The
cost is that SCHEMA must track `src/models.py` — `tests/test_migrate_db.py`
enforces that, failing if a model column has no counterpart here.

There is no Alembic / Flask-Migrate in this project. Note that
`db.create_all()` (src/app.py) creates missing *tables* only and will never add
a column to an existing one — that gap is exactly what this script fills. Run
it after pulling code that changes `models.py`, before `docker compose up`.

Usage:
    python3 migrate_db.py --dry-run             # print the plan, write nothing
    python3 migrate_db.py --yes                 # apply, no confirmation prompt
    python3 migrate_db.py --db path/to/tasks.db # override the DB path
    python3 migrate_db.py path/to/tasks.db      # positional form, equivalent

Default DB path: ./instance/tasks.db (relative to this file).
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'instance', 'tasks.db')

# Expected schema, mirroring src/models.py. Per table: the CREATE statement
# used when the table is missing entirely, the per-column definitions used for
# ALTER TABLE ADD COLUMN when only a column is missing, and any indexes.
#
# Column DDL note: SQLite cannot ADD COLUMN with NOT NULL and no DEFAULT to a
# non-empty table. Model columns that are `nullable=False` with a Python-side
# `default=` therefore carry an explicit SQL DEFAULT here (e.g. `status`), which
# a create_all()-fresh DB does not have. Harmless — SQLAlchemy always supplies
# the value on insert; the DEFAULT only exists to make the backfill legal.
SCHEMA = {
    'tasks': {
        'create': """
            CREATE TABLE tasks (
                id INTEGER NOT NULL PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                description TEXT,
                space VARCHAR(100),
                space_id INTEGER REFERENCES spaces(id),
                priority FLOAT,
                deadline DATETIME,
                estimated_duration INTEGER,
                scheduled_start DATETIME,
                scheduled_end DATETIME,
                status VARCHAR(20) NOT NULL DEFAULT 'todo',
                completed BOOLEAN,
                completed_at DATETIME,
                frozen BOOLEAN,
                note_id INTEGER REFERENCES notes(id) ON DELETE SET NULL,
                created_at DATETIME,
                updated_at DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'title': 'VARCHAR(500) NOT NULL',
            'description': 'TEXT',
            'space': 'VARCHAR(100)',
            'space_id': 'INTEGER REFERENCES spaces(id)',
            'priority': 'FLOAT',
            'deadline': 'DATETIME',
            'estimated_duration': 'INTEGER',
            'scheduled_start': 'DATETIME',
            'scheduled_end': 'DATETIME',
            'status': "VARCHAR(20) NOT NULL DEFAULT 'todo'",
            'completed': 'BOOLEAN',
            'completed_at': 'DATETIME',
            'frozen': 'BOOLEAN',
            'note_id': 'INTEGER REFERENCES notes(id) ON DELETE SET NULL',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        },
    },
    'subtasks': {
        'create': """
            CREATE TABLE subtasks (
                id INTEGER NOT NULL PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                title VARCHAR(500) NOT NULL,
                done BOOLEAN NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'task_id': 'INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE',
            'title': 'VARCHAR(500) NOT NULL',
            'done': 'BOOLEAN NOT NULL DEFAULT 0',
            'position': 'INTEGER NOT NULL DEFAULT 0',
            'created_at': 'DATETIME',
        },
        'indexes': {
            'ix_subtasks_task_id':
                'CREATE INDEX ix_subtasks_task_id ON subtasks (task_id)',
        },
    },
    'spaces': {
        'create': """
            CREATE TABLE spaces (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                context_markdown TEXT,
                time_constraints TEXT,
                created_at DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'name': 'VARCHAR(100) NOT NULL UNIQUE',
            'description': 'TEXT',
            'context_markdown': 'TEXT',
            'time_constraints': 'TEXT',
            'created_at': 'DATETIME',
        },
    },
    'change_logs': {
        'create': """
            CREATE TABLE change_logs (
                id INTEGER NOT NULL PRIMARY KEY,
                action VARCHAR(100) NOT NULL,
                entity_type VARCHAR(50) NOT NULL,
                entity_id INTEGER,
                old_value TEXT,
                new_value TEXT,
                actor VARCHAR(50) DEFAULT 'user',
                timestamp DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'action': 'VARCHAR(100) NOT NULL',
            'entity_type': 'VARCHAR(50) NOT NULL',
            'entity_id': 'INTEGER',
            'old_value': 'TEXT',
            'new_value': 'TEXT',
            'actor': "VARCHAR(50) DEFAULT 'user'",
            'timestamp': 'DATETIME',
        },
    },
    'notes': {
        'create': """
            CREATE TABLE notes (
                id INTEGER NOT NULL PRIMARY KEY,
                space_id INTEGER NOT NULL REFERENCES spaces(id),
                title VARCHAR(500),
                content_markdown TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'space_id': 'INTEGER NOT NULL REFERENCES spaces(id)',
            'title': 'VARCHAR(500)',
            'content_markdown': 'TEXT',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        },
    },
    'mailboxes': {
        'create': """
            CREATE TABLE mailboxes (
                id INTEGER NOT NULL PRIMARY KEY,
                label VARCHAR(100) NOT NULL,
                host VARCHAR(255) NOT NULL,
                port INTEGER,
                username VARCHAR(255) NOT NULL,
                password_encrypted TEXT NOT NULL,
                use_ssl BOOLEAN,
                space_id INTEGER REFERENCES spaces(id),
                created_at DATETIME,
                updated_at DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'label': 'VARCHAR(100) NOT NULL',
            'host': 'VARCHAR(255) NOT NULL',
            'port': 'INTEGER',
            'username': 'VARCHAR(255) NOT NULL',
            'password_encrypted': 'TEXT NOT NULL',
            'use_ssl': 'BOOLEAN',
            'space_id': 'INTEGER REFERENCES spaces(id)',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        },
    },
    'calendar_sources': {
        'create': """
            CREATE TABLE calendar_sources (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                ics_url VARCHAR(500) NOT NULL,
                enabled BOOLEAN,
                created_at DATETIME,
                last_fetched DATETIME
            )
        """,
        'columns': {
            'id': 'INTEGER NOT NULL PRIMARY KEY',
            'name': 'VARCHAR(100) NOT NULL',
            'ics_url': 'VARCHAR(500) NOT NULL',
            'enabled': 'BOOLEAN',
            'created_at': 'DATETIME',
            'last_fetched': 'DATETIME',
        },
    },
}

# Idempotent data fixups, applied after the schema diff. Each is
# (description, SQL) and must be safe to run any number of times — the WHERE
# clause always excludes rows already carrying the target value.
DATA_FIXUPS = [
    # The legacy `tasks.space` name string predates the spaces table; the FK is
    # canonical. Only fills rows that never got one.
    ("backfill tasks.space_id from the legacy tasks.space name", """
        UPDATE tasks
           SET space_id = (SELECT s.id FROM spaces s WHERE s.name = tasks.space)
         WHERE space_id IS NULL
           AND space IS NOT NULL
           AND EXISTS (SELECT 1 FROM spaces s WHERE s.name = tasks.space)
    """),
    # Kanban status arrived after `completed`; derive it for pre-kanban rows.
    ("backfill tasks.status='done' for completed tasks", """
        UPDATE tasks SET status = 'done' WHERE completed = 1 AND status != 'done'
    """),
    ("backfill tasks.status='todo' where NULL or empty", """
        UPDATE tasks SET status = 'todo' WHERE status IS NULL OR status = ''
    """),
    # No historical finish time exists for pre-existing done tasks; updated_at
    # is the closest honest approximation and keeps the Overview "Show done"
    # ordering from collapsing on NULLs.
    ("backfill tasks.completed_at from updated_at for done tasks", """
        UPDATE tasks SET completed_at = updated_at
         WHERE completed = 1 AND completed_at IS NULL
    """),
    # Rows written before agent attribution existed were all user-made.
    ("backfill change_logs.actor='user' where NULL", """
        UPDATE change_logs SET actor = 'user' WHERE actor IS NULL
    """),
]


def backup_db(db_path):
    """Copy the DB next to itself with a timestamped .bak suffix."""
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = f"{db_path}.bak-{stamp}"
    shutil.copy2(db_path, backup_path)
    print(f"Backup written: {backup_path}")
    return backup_path


def table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def index_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row is not None


def column_names(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def row_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def plan_schema(conn):
    """Return the additive DDL statements needed to reconcile the DB.

    Each entry is (description, sql). Tables come first so a column added to a
    table created in the same run is impossible (a fresh CREATE is complete).
    """
    steps = []
    for table, spec in SCHEMA.items():
        if not table_exists(conn, table):
            steps.append((f"create table {table}", spec['create'].strip()))
            for index_name, index_ddl in spec.get('indexes', {}).items():
                steps.append((f"create index {index_name}", index_ddl))
            continue

        existing = column_names(conn, table)
        for column, ddl in spec['columns'].items():
            if column in existing:
                continue
            # SQLite rejects ADD COLUMN NOT NULL without a DEFAULT on a
            # non-empty table. Fail loudly rather than half-migrating.
            if 'NOT NULL' in ddl and 'DEFAULT' not in ddl and row_count(conn, table):
                raise SystemExit(
                    f"ERROR: cannot add {table}.{column} ({ddl}) to a non-empty "
                    "table — NOT NULL without a DEFAULT. Give the column an SQL "
                    "DEFAULT in SCHEMA, or migrate this table by hand.")
            steps.append((f"add column {table}.{column}",
                          f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))

        for index_name, index_ddl in spec.get('indexes', {}).items():
            if not index_exists(conn, index_name):
                steps.append((f"create index {index_name}", index_ddl))
    return steps


def verify(conn):
    """Re-read the schema and assert the diff is now empty."""
    problems = []
    for table, spec in SCHEMA.items():
        if not table_exists(conn, table):
            problems.append(f"table {table} still missing")
            continue
        existing = column_names(conn, table)
        missing = [c for c in spec['columns'] if c not in existing]
        if missing:
            problems.append(f"{table} still missing columns {missing}")
    if problems:
        raise SystemExit(
            "ERROR: schema still incomplete after migration — manual "
            "inspection needed (the backup is untouched):\n  "
            + "\n  ".join(problems))
    print("OK: every expected table and column is present.")


def migrate(db_path, dry_run=False):
    conn = sqlite3.connect(db_path)
    try:
        if not table_exists(conn, 'tasks'):
            raise SystemExit(
                f"ERROR: {db_path} has no 'tasks' table — is this the right database?")

        steps = plan_schema(conn)
        if steps:
            print(f"Schema diff: {len(steps)} statement(s)")
            for description, sql in steps:
                print(f"  - {description}")
                if not dry_run:
                    conn.execute(sql)
        else:
            print("Schema already up to date — no DDL needed.")

        if dry_run:
            print("\nData fixups that would run (idempotent):")
            for description, _ in DATA_FIXUPS:
                print(f"  - {description}")
            print("\nDry run — nothing written.")
            return

        conn.commit()

        print("Data fixups:")
        for description, sql in DATA_FIXUPS:
            cursor = conn.execute(sql)
            print(f"  - {description}: {cursor.rowcount} row(s)")
        conn.commit()

        verify(conn)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Additive-only schema reconciler for the prod SQLite DB.")
    parser.add_argument('db_path_positional', nargs='?', metavar='DB_PATH',
                        help="path to tasks.db (same as --db)")
    parser.add_argument('--db', dest='db_path',
                        help=f"path to tasks.db (default: {DEFAULT_DB})")
    parser.add_argument('--dry-run', action='store_true',
                        help="print the plan, write nothing")
    parser.add_argument('--yes', action='store_true',
                        help="skip the confirmation prompt")
    args = parser.parse_args()

    if args.db_path and args.db_path_positional:
        raise SystemExit("ERROR: pass the DB path once — either --db or positionally.")
    db_path = args.db_path or args.db_path_positional or DEFAULT_DB

    if not os.path.isfile(db_path):
        raise SystemExit(f"ERROR: database not found at {db_path}")
    if not args.dry_run and not os.access(db_path, os.W_OK):
        raise SystemExit(
            f"ERROR: {db_path} is not writable — re-run with the owning user "
            "(or `sudo`), or fix the file permissions.")

    print(f"Migrating {db_path}")

    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit(
                "ERROR: not a terminal — pass --yes to apply, or --dry-run to preview.")
        answer = input("Apply the migration? A timestamped backup is taken first. [y/N] ")
        if answer.strip().lower() not in ('y', 'yes'):
            raise SystemExit("Aborted — nothing written.")

    if not args.dry_run:
        backup_db(db_path)
    migrate(db_path, dry_run=args.dry_run)
    if not args.dry_run:
        print("Migration complete.")


if __name__ == '__main__':
    main()
