# Data Model

> SQLAlchemy models in `src/models.py`. SQLite file at `instance/tasks.db` (gitignored, Docker-mounted under `/app/instance`). This is the authoritative shape; `doc/PROJECT_DESCRIPTION.md` mirrors it but code is the source of truth.

## Tables

### `tasks`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | auto-increment |
| title | String(500) NOT NULL | |
| description | Text | nullable |
| space | String(100) | **DEPRECATED** — legacy category name, kept for backward compat; use `space_id` |
| space_id | INTEGER FK → spaces.id | current relation |
| priority | INTEGER default 0 | 0-10, higher = more urgent |
| deadline | DateTime | nullable, ISO |
| estimated_duration | INTEGER | minutes (scheduler falls back to 60) |
| scheduled_start / scheduled_end | DateTime | set by `schedule_tasks` |
| completed | Boolean default False | |
| frozen | Boolean default False | pins slot; excluded from reschedule but still blocks others |
| created_at / updated_at | DateTime | utcnow / onupdate utcnow |

`to_dict()` returns a `space` (name) field resolved from `space_rel` if present, falling back to the legacy `space` string — so the UI/API always sees a space name even though the canonical link is `space_id`.

### `spaces`
`id`, `name` (unique), `description` (Text, helps AI infer context), `time_constraints` (Text — JSON string), `created_at`. Helpers `get_time_constraints()` / `set_time_constraints()` round-trip the JSON. Default spaces seeded: `work` (Mon-Fri 09-17), `study` (no constraints), `association` (Wed 18-22).

**time_constraints JSON shape:**
```json
[{"day": 0, "start": "09:00", "end": "17:00"}]  // 0=Mon ... 6=Sun
```

### `change_logs`
Audit trail: `action` (create/update/delete/reorder/freeze/reschedule), `entity_type` (task/space), `entity_id`, `old_value` / `new_value` (JSON strings), `timestamp`. Intended for future ML preference learning; written opportunistically from app.py handlers.

### `calendar_sources`
`id`, `name`, `ics_url`, `enabled`, `created_at`, `last_fetched`. No scheduling of fetches — `/api/external-events` calls `fetch_external_events` live per request.

## Schema management caveat
There is **no migration framework** (no Alembic / Flask-Migrate). Tables are created via `db.create_all()` at app startup; schema changes require manual `migrate.py`-style scripts against the prod SQLite file (an explicit open TODO in `doc/TODO.md`). When touching `models.py`, assume existing prod dbs need a hand-written migration.
