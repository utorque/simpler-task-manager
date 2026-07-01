#!/usr/bin/env python3
"""
migrate_db.py — hand-rolled, additive-only schema reconciler.

Compares the model-defined schema (`db.metadata` in `src/models.py`) against
the actual SQLite database file and applies the *additive* diff:

  1. CREATE missing tables (e.g. `notes` landing on a prod DB that predates it).
  2. ALTER TABLE ADD COLUMN for columns present on the model but absent in the DB.

It NEVER drops tables, columns, or data. It is idempotent — running it twice is
a no-op the second time. Use it before `docker compose up` after pulling code
that introduces schema changes. Safe to run on a running server (SQLite tolerates
concurrent readers; the migration itself is a few DDL statements under a brief
lock).

After the schema diff it runs DATA FIXUPS: idempotent UPDATE statements that
backfill new/canonical columns from legacy ones (e.g. `tasks.space_id` from the
deprecated `tasks.space` name string). Each fixup only touches rows where the
target is still unset, so re-running never overwrites user data.

There is no Alembic / Flask-Migrate in this project (data-model topic). This
script is the supported alternative: a deliberate, minimal diff applier that
matches the project's no-migration-framework posture.

Usage:
    python migrate_db.py                 # auto-detect DB, prompt to confirm
    python migrate_db.py --dry-run      # print the plan, write nothing
    python migrate_db.py --yes          # skip the confirmation prompt
    python migrate_db.py --db /path/to/tasks.db   # override DB path

The DB path auto-detect order:
    1. --db PATH (explicit)
    2. instance/tasks.db      (Flask-SQLAlchemy instance-relative default;
                               resolves to ./instance/tasks.db under the
                               Docker WORKDIR /app, or ./instance/tasks.db
                               when run from the repo root)
    3. tasks.db               (last-resort CWD fallback)
    4. the file Config.SQLALCHEMY_DATABASE_URI points at, if absolute
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `src/` importable so `from models import db` resolves the same way it
# does under `PYTHONPATH=/app` (Dockerfile) — without booting the Flask app.
HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.dialects import sqlite as sqlite_dialect  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# Importing `db` + models populates `db.metadata` at class-definition time.
# This does NOT import `app.py` (which would trigger import-time create_all +
# seeding against the prod DB); we only import the model module.
from models import db  # noqa: E402


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def resolve_db_path(explicit: str | None) -> Path:
    """Find the SQLite file to migrate."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            sys.exit(f"[migrate] DB file not found: {p} (use --db to point at it)")
        return p

    # Try the instance-relative locations the app actually uses.
    candidates = [
        HERE / "instance" / "tasks.db",
        HERE / "tasks.db",
        SRC / "instance" / "tasks.db",
    ]

    # Also honour whatever Config points at, if it's an absolute file path.
    try:
        from config import Config  # noqa: WPS433
        uri = getattr(Config, "SQLALCHEMY_DATABASE_URI", "")
        # sqlite:///abs/path  ->  /abs/path   ;  sqlite:///rel  ->  <cwd>/rel
        if uri.startswith("sqlite:///"):
            rest = uri[len("sqlite:///"):]
            cand = Path(rest) if os.path.isabs(rest) else (HERE / rest)
            candidates.append(cand)
    except Exception:  # noqa: BLE001 — Config import is best-effort
        pass

    for cand in candidates:
        if cand.exists():
            return cand.resolve()

    sys.exit(
        "[migrate] No SQLite DB file found. Looked for:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\nPass --db /path/to/tasks.db explicitly."
    )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def column_ddl(col) -> str:
    """Render a column's type for use in an ALTER TABLE ADD COLUMN statement."""
    return col.type.compile(dialect=sqlite_dialect.dialect())


def column_default_for(col):
    """
    SQLite `ALTER TABLE ADD COLUMN` needs a DEFAULT for NOT NULL columns on a
    non-empty table. Synthesize a safe, type-appropriate literal.
    Returns None when no default is needed (nullable column).
    """
    if col.nullable:
        return None

    type_name = type(col.type).__name__.upper()
    if type_name in {"BOOLEAN", "BOOL"}:
        return "0" if col.default is None else ("1" if _truthy_default(col) else "0")
    if type_name in {"INTEGER", "INT", "BIGINT", "SMALLINT"}:
        return str(int(getattr(col.default, "arg", 0) or 0)) if col.default else "0"
    if type_name in {"STRING", "VARCHAR", "NVARCHAR", "TEXT", "CHAR"}:
        if col.default is not None:
            arg = getattr(col.default, "arg", "")
            return "'" + str(arg).replace("'", "''") + "'"
        return "''"
    # DateTime and anything else: fall back to CURRENT_TIMESTAMP so NOT NULL
    # is satisfiable without inventing a bogus value.
    return "CURRENT_TIMESTAMP"


def _truthy_default(col) -> bool:
    arg = getattr(col.default, "arg", None) if col.default else None
    return bool(arg)


def diff(engine):
    """
    Compute the additive diff between db.metadata (desired) and the DB (actual).
    Returns (missing_tables: list[Table], missing_columns: list[(table, col)]).
    Does NOT detect extra/dropped schema or type drift — additive-only by design.
    """
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())

    missing_tables = []
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            missing_tables.append(table)

    missing_columns = []
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # whole table will be CREATEd
        existing_cols = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing_cols:
                missing_columns.append((table, col))

    return missing_tables, missing_columns


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_diff(engine, missing_tables, missing_columns, dry_run: bool) -> None:
    """Execute the additive DDL. Each statement in its own transaction."""
    if not missing_tables and not missing_columns:
        return

    # Whole missing tables — let SQLAlchemy emit the CREATE TABLE (incl. FKs,
    # indexes, etc.). create_all is idempotent and only creates what's missing.
    if missing_tables:
        names = ", ".join(t.name for t in missing_tables)
        print(f"[migrate] CREATE missing table(s): {names}")
        if not dry_run:
            db.metadata.create_all(
                engine,
                tables=[t for t in missing_tables],
            )

    # Missing columns on existing tables — ALTER TABLE ADD COLUMN one at a time.
    for table, col in missing_columns:
        default = column_default_for(col)
        # NOT NULL columns need a default when added against a non-empty table.
        not_null = " NOT NULL" if not col.nullable else ""
        default_clause = f" DEFAULT {default}" if default is not None else ""
        stmt = (
            f'ALTER TABLE "{table.name}" '
            f'ADD COLUMN "{col.name}" {column_ddl(col)}'
            f"{not_null}{default_clause}"
        )
        print(f"[migrate] {stmt}")
        if not dry_run:
            with engine.begin() as conn:
                conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# Data fixups
# ---------------------------------------------------------------------------

# (description, SQL) pairs, run AFTER the schema diff so new columns exist.
# Every statement MUST be idempotent: guard on the target being unset.
DATA_FIXUPS = [
    (
        "backfill tasks.space_id from the legacy tasks.space name string",
        """
        UPDATE tasks
           SET space_id = (SELECT id FROM spaces WHERE spaces.name = tasks.space)
         WHERE space_id IS NULL
           AND space IS NOT NULL
           AND EXISTS (SELECT 1 FROM spaces WHERE spaces.name = tasks.space)
        """,
    ),
]


def apply_data_fixups(engine, dry_run: bool) -> None:
    """Run the idempotent data backfills. Each in its own transaction."""
    for description, sql in DATA_FIXUPS:
        print(f"[migrate] data fixup: {description}")
        if dry_run:
            continue
        with engine.begin() as conn:
            result = conn.execute(text(sql))
            print(f"[migrate]   -> {result.rowcount} row(s) updated")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", help="Path to the SQLite DB file (auto-detected otherwise).")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, write nothing.")
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = ap.parse_args()

    db_path = resolve_db_path(args.db)
    uri = f"sqlite:///{db_path}"
    # StaticPool keeps a single connection so DDL statements see a consistent
    # view of the file (matches the test-harness pattern).
    engine = create_engine(uri, connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)

    print(f"[migrate] DB:    {db_path}")
    print(f"[migrate] URI:   {uri}")
    print(f"[migrate] mode:  {'DRY-RUN' if args.dry_run else 'APPLY'}")

    missing_tables, missing_columns = diff(engine)

    if not missing_tables and not missing_columns:
        print("[migrate] Schema is up to date.")
    else:
        # Show the plan up front.
        for t in missing_tables:
            cols = ", ".join(c.name for c in t.columns)
            print(f"  + table  {t.name} ({cols})")
        for table, col in missing_columns:
            print(f"  + column {table.name}.{col.name} ({column_ddl(col)})")

    if args.dry_run:
        apply_data_fixups(engine, dry_run=True)
        print("[migrate] dry-run — no changes written.")
        return

    if (missing_tables or missing_columns) and not args.yes:
        print()
        resp = input("[migrate] Apply these changes? [y/N] ").strip().lower()
        if resp not in {"y", "yes"}:
            print("[migrate] aborted.")
            return

    apply_diff(engine, missing_tables, missing_columns, dry_run=False)
    # Data fixups run after DDL so freshly added columns exist; they are
    # idempotent, so running them on every invocation is safe.
    apply_data_fixups(engine, dry_run=False)
    print("[migrate] done.")


if __name__ == "__main__":
    main()
