# Data Model

> SQLAlchemy models in `src/models.py`. SQLite file at `instance/tasks.db` (gitignored, Docker-mounted under `/app/instance`). This is the authoritative shape; `doc/PROJECT_DESCRIPTION.md` mirrors it but code is the source of truth.

## Tables

### `tasks`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | auto-increment |
| title | String(500) NOT NULL | |
| description | Text | nullable |
| space | String(100) | **LEGACY, unused by code** — column kept only because migrations are additive; data backfilled into `space_id` by `migrate_db.py` |
| space_id | INTEGER FK → spaces.id | canonical relation |
| priority | INTEGER default 0 | 0-10, higher = more urgent |
| deadline | DateTime | nullable, ISO |
| estimated_duration | INTEGER | minutes (scheduler falls back to 60) |
| scheduled_start / scheduled_end | DateTime | set by `schedule_tasks` |
| status | String(20) NOT NULL default 'todo' | kanban state: `todo / doing / blocked / done` (`TASK_STATUSES` in models.py) |
| completed | Boolean default False | kept in sync: completed ⇔ status == 'done' |
| completed_at | DateTime | stamped on first transition into done (`_sync_completed_at`), kept on re-saves of a done task, cleared on leaving done |
| frozen | Boolean default False | pins slot; excluded from reschedule but still blocks others. Orthogonal to status |
| created_at / updated_at | DateTime | utcnow / onupdate utcnow |

**Status invariant**: `status` is the single source of truth for done-ness; `Task.apply_status()` / `Task.apply_completed()` keep the pair consistent (writing `completed` derives status — `done`, or `todo` when un-completing; when a request carries both, status wins). Routes validate status and 400 unknown values.

`to_dict()` returns a `space` (name) field denormalized from `space_rel` — the UI/API sees a space name but the canonical link is `space_id`. The legacy `space` string is never read.

### `spaces`
`id`, `name` (unique), `description` (Text, helps AI infer context), `time_constraints` (Text — JSON string), `created_at`. Helpers `get_time_constraints()` / `set_time_constraints()` round-trip the JSON. Default spaces seeded: `work` (Mon-Fri 09-17), `study` (no constraints), `association` (Wed 18-22).

**time_constraints JSON shape:**
```json
[{"day": 0, "start": "09:00", "end": "17:00"}]  // 0=Mon ... 6=Sun
```

### `change_logs`
Audit trail: `action` (create/update/delete/reorder/freeze/unfreeze), `entity_type` (**task/space/note/mailbox**), `entity_id`, `old_value` / `new_value` (JSON strings — always full `to_dict()` snapshots), `actor` (**'user' or 'ai'** — AI-created tasks log `actor='ai'`), `timestamp`. Intended for future ML preference learning.

All writers go through **`audit.record_change(action, entity_type, entity_id, old=, new=, actor=)`** which queues the row in the CURRENT session so entity mutation + audit land in one transaction (the route commits once). Do not hand-roll ChangeLog stanzas in routes.

### `calendar_sources`
`id`, `name`, `ics_url`, `enabled`, `created_at`, `last_fetched`. No scheduling of fetches — `/api/external-events` calls `fetch_external_events` live per request.

### `notes`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | auto-increment |
| space_id | INTEGER FK → spaces.id | **NOT NULL** — every note belongs to a Space; no "unfiled" pseudo-space |
| title | String(500) | nullable — empty title is a valid stored state; the list UI falls back to "Untitled" |
| content_markdown | Text default '' | raw markdown source (the editor is a markdown source editor, not WYSIWYG) |
| created_at / updated_at | DateTime | utcnow / onupdate utcnow |

`Note` model (`src/models.py`) declares `space_rel = db.relationship('Space', backref='notes', foreign_keys=[space_id])` — the canonical Space link; promote-to-task reads `note.space_rel` when injecting Space context into the Cleanify prompt. `to_dict()` returns `{id, space_id, title, content_markdown, created_at, updated_at}` (title returned as-is, including `None`).

Notes mutations log to `change_logs` with `entity_type='note'`, `action` in `{create, update, delete}`, JSON-serialized `Note.to_dict()` snapshots in `old_value`/`new_value` — a Cleanify Apply is just an ordinary `update`. Promote-to-task does NOT log here; it flows through the existing `POST /api/tasks` path and logs as `entity_type='task', action='create'`.

**Intentional absence:** there is NO `source_note_id` column on `tasks`. The link between a promoted task and its source note is conceptual only (PRD `001` Out-of-Scope 4) — a future "jump from task to note" affordance can be added later as a nullable FK if it turns out to matter.

### `mailboxes`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| label | String(100) NOT NULL | display name |
| host / port | String(255) / INTEGER default 993 | IMAP server |
| username | String(255) NOT NULL | |
| password_encrypted | Text NOT NULL | Fernet-encrypted (`crypto_utils`, key derived from SECRET_KEY) |
| use_ssl | Boolean default True | False = plain IMAP + STARTTLS attempt |
| space_id | INTEGER FK → spaces.id | nullable; the Space email-derived tasks inherit |
| created_at / updated_at | DateTime | |

No inbox contents persisted — live IMAP fetch per request (mirrors calendar_sources' live-ICS). `to_dict()` exposes `has_password` only; **passwords never leave the server**. Rotating SECRET_KEY orphans stored passwords (messages endpoints answer 409; user re-enters).

## Schema management
There is **no migration framework** (no Alembic / Flask-Migrate). Tables are created via `db.create_all()` at app startup for fresh DBs; existing prod DBs are migrated with **`migrate_db.py`** (repo root): an additive-only diff applier (CREATE missing tables, ADD COLUMN missing columns) followed by **idempotent data fixups** (`DATA_FIXUPS`: backfill `tasks.space_id` from the legacy name string, backfill `tasks.status` from `completed`, backfill `tasks.completed_at` from `updated_at` for already-done rows). When adding a column that needs a data backfill, add a guarded UPDATE to `DATA_FIXUPS` in the same change.
