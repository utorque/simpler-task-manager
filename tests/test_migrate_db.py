"""migrate_db.py drift guard + end-to-end migration of an old-shape DB.

Background (2026-07): `migrate_db.py` was once a generic model-metadata-vs-DB
reconciler, then got rewritten into a hand-listed two-step script. The rewrite
silently dropped the `tasks.status` migration, so every DB predating the kanban
workflow 500'd on `GET /api/tasks` ("no such column: tasks.status") with no
supported way to move it forward — `db.create_all()` only ever creates missing
*tables*, never adds a column to an existing one.

The script is stdlib-only by design (copyable to a server with no venv), so it
carries a hand-written SCHEMA instead of importing `db.metadata`. These tests
are what keeps that copy honest: the first two fail the moment models.py and
SCHEMA disagree in either direction.
"""

import sqlite3

import migrate_db
from models import db


def _model_tables():
    return {table.name: {c.name for c in table.columns}
            for table in db.metadata.sorted_tables}


# ===== drift guard: SCHEMA must mirror models.py =====

def test_schema_covers_every_model_table(app):
    missing = set(_model_tables()) - set(migrate_db.SCHEMA)
    assert not missing, (
        f"models.py defines tables absent from migrate_db.SCHEMA: {sorted(missing)} — "
        "a fresh install gets them from create_all(), but no existing DB ever will.")


def test_schema_columns_match_model_columns(app):
    for table, model_columns in _model_tables().items():
        script_columns = set(migrate_db.SCHEMA[table]['columns'])
        assert model_columns - script_columns == set(), (
            f"{table}: columns in models.py but not migrate_db.SCHEMA: "
            f"{sorted(model_columns - script_columns)} — existing DBs will 500 on them.")
        assert script_columns - model_columns == set(), (
            f"{table}: columns in migrate_db.SCHEMA but not models.py: "
            f"{sorted(script_columns - model_columns)} — stale entry, drop it.")


def test_create_ddl_and_column_ddl_agree(app):
    """A missing table and a missing column must yield the same final schema."""
    for table, spec in migrate_db.SCHEMA.items():
        conn = sqlite3.connect(':memory:')
        conn.execute(spec['create'])
        created = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        conn.close()
        assert created == set(spec['columns']), (
            f"{table}: CREATE statement and 'columns' map disagree — "
            f"create-only={sorted(created - set(spec['columns']))}, "
            f"columns-only={sorted(set(spec['columns']) - created)}")


# ===== end-to-end: a pre-kanban DB is brought forward =====

# The tasks table as it existed before the kanban workflow: no status, no
# completed_at, no note_id.
OLD_TASKS_DDL = """
    CREATE TABLE tasks (
        id INTEGER NOT NULL PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        space VARCHAR(100),
        space_id INTEGER,
        priority FLOAT,
        deadline DATETIME,
        estimated_duration INTEGER,
        scheduled_start DATETIME,
        scheduled_end DATETIME,
        completed BOOLEAN,
        frozen BOOLEAN,
        created_at DATETIME,
        updated_at DATETIME
    )
"""


def _old_db(tmp_path):
    """A DB shaped like production before the kanban migration."""
    path = tmp_path / 'tasks.db'
    conn = sqlite3.connect(path)
    conn.execute(OLD_TASKS_DDL)
    conn.execute("CREATE TABLE spaces (id INTEGER PRIMARY KEY, name VARCHAR(100))")
    conn.execute("INSERT INTO spaces (id, name) VALUES (1, 'Work')")
    conn.execute(
        "INSERT INTO tasks (id, title, space, space_id, completed, updated_at) "
        "VALUES (1, 'done one', 'Work', NULL, 1, '2026-01-01 10:00:00')")
    conn.execute(
        "INSERT INTO tasks (id, title, space, space_id, completed, updated_at) "
        "VALUES (2, 'open one', 'Work', NULL, 0, '2026-01-02 10:00:00')")
    conn.commit()
    conn.close()
    return str(path)


def _columns(path, table):
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def test_migrate_adds_every_missing_column(app, tmp_path):
    path = _old_db(tmp_path)
    migrate_db.migrate(path)
    columns = _columns(path, 'tasks')
    for expected in ('status', 'completed_at', 'note_id'):
        assert expected in columns


def test_migrate_creates_missing_tables(app, tmp_path):
    path = _old_db(tmp_path)
    migrate_db.migrate(path)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {'subtasks', 'notes', 'mailboxes', 'change_logs'} <= tables


def test_migrate_backfills_status_and_completed_at(app, tmp_path):
    path = _old_db(tmp_path)
    migrate_db.migrate(path)
    conn = sqlite3.connect(path)
    rows = dict(conn.execute("SELECT id, status FROM tasks"))
    completed_at = dict(conn.execute("SELECT id, completed_at FROM tasks"))
    conn.close()
    assert rows[1] == 'done'      # completed=1 → status done
    assert rows[2] == 'todo'      # ADD COLUMN default
    assert completed_at[1] == '2026-01-01 10:00:00'  # from updated_at
    assert completed_at[2] is None


def test_migrate_backfills_space_id_from_legacy_space_name(app, tmp_path):
    path = _old_db(tmp_path)
    migrate_db.migrate(path)
    conn = sqlite3.connect(path)
    space_ids = dict(conn.execute("SELECT id, space_id FROM tasks"))
    conn.close()
    assert space_ids[1] == 1
    assert space_ids[2] == 1


def test_migrate_is_idempotent(app, tmp_path):
    path = _old_db(tmp_path)
    migrate_db.migrate(path)
    first = _columns(path, 'tasks')
    migrate_db.migrate(path)  # must not raise
    assert _columns(path, 'tasks') == first


def test_dry_run_writes_nothing(app, tmp_path):
    path = _old_db(tmp_path)
    before = _columns(path, 'tasks')
    migrate_db.migrate(path, dry_run=True)
    assert _columns(path, 'tasks') == before
