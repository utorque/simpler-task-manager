#!/usr/bin/env python3
"""Standalone production-DB migration for simpler-smart-calendar.

Backs up the SQLite database, then applies additive, idempotent schema
changes. Safe to run multiple times; needs only the Python standard library
(no Flask/SQLAlchemy), so it can be copied to and run on the server as-is.

Usage:
    python3 migrate_db.py [path/to/tasks.db]

Default DB path: ./instance/tasks.db (relative to this file).

Migrations:
    2026-07  subtasks table (checklist items under a task)
    2026-07  tasks.note_id column (provenance link: task promoted from a note)
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'instance', 'tasks.db')

SUBTASKS_DDL = """
CREATE TABLE IF NOT EXISTS subtasks (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    done BOOLEAN NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME
)
"""

SUBTASKS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS ix_subtasks_task_id ON subtasks (task_id)
"""


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


def column_names(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def migrate(db_path):
    conn = sqlite3.connect(db_path)
    try:
        if not table_exists(conn, 'tasks'):
            raise SystemExit(
                f"ERROR: {db_path} has no 'tasks' table — is this the right database?")

        if table_exists(conn, 'subtasks'):
            print("subtasks table already present — nothing to do.")
        else:
            conn.execute(SUBTASKS_DDL)
            conn.execute(SUBTASKS_INDEX_DDL)
            conn.commit()
            print("Created subtasks table (+ index on task_id).")

        if 'note_id' in column_names(conn, 'tasks'):
            print("tasks.note_id already present — nothing to do.")
        else:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN note_id INTEGER REFERENCES notes(id)")
            conn.commit()
            print("Added tasks.note_id column.")

        # Sanity check the final schema.
        cols = column_names(conn, 'subtasks')
        expected = ['id', 'task_id', 'title', 'done', 'position', 'created_at']
        missing = [c for c in expected if c not in cols]
        if missing:
            raise SystemExit(
                f"ERROR: subtasks table is missing columns {missing} — "
                "manual inspection needed (backup is untouched).")
        print(f"OK: subtasks columns = {cols}")
        if 'note_id' not in column_names(conn, 'tasks'):
            raise SystemExit(
                "ERROR: tasks.note_id still missing after migration — "
                "manual inspection needed (backup is untouched).")
        print("OK: tasks.note_id present")
    finally:
        conn.close()


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    if not os.path.isfile(db_path):
        raise SystemExit(f"ERROR: database not found at {db_path}")
    print(f"Migrating {db_path}")
    backup_db(db_path)
    migrate(db_path)
    print("Migration complete.")


if __name__ == '__main__':
    main()
