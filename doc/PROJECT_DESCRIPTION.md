# Simpler — Unified ADHD-Friendly Workspace

> **Note**: This document should be kept up to date with all code changes, feature additions, and architectural modifications. Code is the source of truth; deep-dive context lives in `.opencode/context/`.

## Project Overview

**Simpler** is an ADHD-friendly, self-hosted workspace that unifies **tasks, calendar, notes, and mail** around a shared *Space* concept (work / study / association / …). The guiding principle: *streamlined, friction-free, all-in-one-place — everything reachable in as few clicks as possible.*

One page, one header, four destinations:

1. **Tasks** (home) — a kanban board (`todo / doing / blocked / done`) with a space-filter chip row, drag-between-columns, and per-column inline create; a grouped-by-space **Overview** is the secondary subview.
2. **Calendar** — AI-parsed tasks auto-scheduled around external ICS events and per-space time constraints (FullCalendar, drag = reschedule + freeze).
3. **Notes** — space-scoped markdown capture (EasyMDE source editor) with debounced autosave, AI **Cleanify** (tidy with undo), and promote-selection-to-task.
4. **Mail** — register IMAP mailboxes linked to Spaces, browse inboxes live, right-click an email → AI-drafted task pre-tagged with the mailbox's Space.

A **global quick-capture input in the header** turns pasted text (emails, thoughts, meeting notes) into structured tasks via an LLM from anywhere in the app.

**Primary Use**: Self-hosted personal task management
**Target Users**: Individuals with ADHD who need simple, fast organization with minimal context switching

## Technology Stack

### Backend
- **Framework**: Flask 3 (app factory + per-domain blueprints)
- **Database**: SQLite with Flask-SQLAlchemy
- **AI**: any OpenAI-compatible endpoint (OpenAI, Mistral, Infomaniak, …) or the Anthropic API — selected at runtime from `AI_API_BASE_URL`
- **Auth**: single shared `APP_PASSWORD`, session cookie
- **Calendar**: `icalendar` for ICS parsing (live fetch, no sync daemon)
- **Mail**: stdlib `imaplib` + `email` (live fetch, nothing persisted)
- **Secrets at rest**: `cryptography` (Fernet) for mailbox passwords

### Frontend
- **UI**: Bootstrap 5, vanilla JS, no build step (CDN assets)
- **Calendar**: FullCalendar.js
- **Drag & Drop**: SortableJS (kanban columns + task list)
- **Markdown editor**: EasyMDE (CodeMirror 5)

### Infrastructure
- **Docker Compose** deploy, port 53000, `./instance` volume for the SQLite file
- **Python 3.11+**

## Project Structure

```
simpler-smart-calendar/
├── migrate_db.py              # Additive schema reconciler + idempotent data fixups (prod SQLite)
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── src/
│   ├── app.py                 # App factory only; registers blueprints
│   ├── models.py              # Task, Space, ChangeLog, Note, Mailbox, CalendarSource
│   ├── routes/                # Per-domain blueprints
│   │   ├── pages.py           # /, /notes (deep link), /login, /logout
│   │   ├── tasks.py           # /api/tasks* (CRUD, parse, freeze, reorder)
│   │   ├── spaces.py          # /api/spaces*
│   │   ├── notes.py           # /api/notes* (CRUD, cleanify, promote-to-task)
│   │   ├── mailboxes.py       # /api/mailboxes* (CRUD, messages, add-task)
│   │   ├── calendar_sources.py# /api/calendar-sources*, /api/external-events
│   │   └── schedule.py        # /api/schedule, /api/logs
│   ├── auth.py                # login_required decorator
│   ├── audit.py               # record_change() — single-transaction ChangeLog seam
│   ├── datetime_utils.py      # parse_iso_datetime
│   ├── prompt_context.py      # system prompt assembly (spaces context)
│   ├── seeding.py             # default spaces (shared with the test harness)
│   ├── scheduler.py           # pure-over-data auto-scheduling (SchedulableTask dicts)
│   ├── ai_parser.py           # AIProvider abstraction + parse/cleanify/email-to-task entry points
│   ├── calendar_integration.py# live ICS fetch
│   ├── mail_integration.py    # live IMAP fetch (transient DTOs)
│   ├── crypto_utils.py        # Fernet encrypt/decrypt derived from SECRET_KEY
│   ├── config.py              # env + prompt loading (cached at startup)
│   ├── prompt.md              # task-parsing system prompt
│   ├── prompts/
│   │   ├── notes_cleanify.md  # Cleanify system prompt
│   │   └── email_to_task.md   # email-to-task system prompt
│   ├── templates/
│   │   ├── index.html         # THE unified shell (all four destinations + modals)
│   │   └── login.html
│   └── static/
│       ├── css/style.css
│       └── js/
│           ├── app.js         # shell: nav, shortcuts, board, calendar, overview, spaces
│           ├── notes.js       # NotesView module (lazy init)
│           ├── mail.js        # MailView module (lazy init)
│           └── task_draft_modal.js # shared AI-draft confirm modal
├── tests/                     # pytest harness + route-layer integration tests
└── doc/                       # this file, README, TODO
```

## Database Schema

### `tasks`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | Auto-incrementing task ID |
| title | STRING(500) | NOT NULL | Task title |
| description | TEXT | NULLABLE | Detailed task description |
| space | STRING(100) | NULLABLE | LEGACY — unused by code; data backfilled into space_id by migrate_db.py |
| space_id | INTEGER | FOREIGN KEY | Canonical reference to spaces.id |
| priority | INTEGER | DEFAULT 0 | Priority 0-10, higher = more urgent |
| deadline | DATETIME | NULLABLE | Task deadline (ISO format) |
| estimated_duration | INTEGER | NULLABLE | Duration in minutes (default 60) |
| scheduled_start / scheduled_end | DATETIME | NULLABLE | Set by the auto-scheduler |
| status | STRING(20) | NOT NULL DEFAULT 'todo' | Kanban state: todo / doing / blocked / done |
| completed | BOOLEAN | DEFAULT FALSE | Kept in sync: completed ⇔ status == 'done' |
| completed_at | DATETIME | NULLABLE | Stamped on the first transition into done; cleared when leaving done; preserved on re-saves of a done task |
| frozen | BOOLEAN | DEFAULT FALSE | Prevents auto-rescheduling (orthogonal to status) |
| created_at / updated_at | DATETIME | | utcnow / onupdate utcnow |

**Status/completed invariant**: `status` is the single source of truth for done-ness. Writing `status='done'` flips `completed=True`; any other status flips it back. Legacy callers writing `completed` get `status` derived (`done`, or `todo` when un-completing). When both are sent, `status` wins.

`to_dict()` echoes `space` (the name) denormalized from the `space_rel` relation — `space_id` is canonical.

### `spaces`
`id`, `name` (unique), `description` (helps the AI infer context), `time_constraints` (JSON string), `created_at`.

**Time constraints format** (day 0=Monday … 6=Sunday):
```json
[
  {"day": 0, "start": "09:00", "end": "17:00"},
  {"day": 2, "start": "18:00", "end": "22:00"}
]
```

Default spaces seeded on first run: `work` (Mon-Fri 9-17), `study` (unconstrained), `association` (Wed 18-22).

### `change_logs`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| action | STRING(100) NOT NULL | create / update / delete / reorder / freeze / unfreeze |
| entity_type | STRING(50) NOT NULL | task / space / note / mailbox |
| entity_id | INTEGER | |
| old_value / new_value | TEXT | JSON snapshots (full `to_dict()` dicts) |
| actor | STRING(50) DEFAULT 'user' | 'user' (direct edits) or 'ai' (AI-created entities) |
| timestamp | DATETIME | |

All mutation routes write through `audit.record_change()` so the entity mutation and its audit row land in **one transaction**.

### `notes`
`id`, `space_id` (FK, **NOT NULL**), `title` (nullable — the list UI falls back to "Untitled"), `content_markdown` (raw markdown source), `created_at` / `updated_at`.

### `mailboxes`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| label | STRING(100) NOT NULL | Display name ("Work inbox") |
| host / port | STRING / INTEGER | IMAP server (default port 993) |
| username | STRING(255) NOT NULL | |
| password_encrypted | TEXT NOT NULL | Fernet-encrypted; key derived from SECRET_KEY |
| use_ssl | BOOLEAN DEFAULT TRUE | False = plain IMAP + STARTTLS attempt |
| space_id | INTEGER FK | The Space email-derived tasks inherit |
| created_at / updated_at | DATETIME | |

No inbox contents are persisted — messages are fetched live per request. `to_dict()` exposes `has_password` only; **no endpoint ever returns a password**. Rotating `SECRET_KEY` invalidates stored passwords (the messages endpoints answer 409 asking for re-entry).

### `calendar_sources`
`id`, `name`, `ics_url`, `enabled`, `created_at`, `last_fetched`. Live-fetched per request (no background sync).

## API Endpoints

All `/api/*` routes require the session cookie (`@login_required`, JSON 401 otherwise).

### Authentication
- `POST /login` — `{password}` → sets session
- `POST /logout`

### Tasks (`src/routes/tasks.py`)
- `GET /api/tasks?include_completed=true|false` — ordered by priority desc, deadline asc
- `POST /api/tasks` — `{title, description?, space_id?, priority?, deadline?, estimated_duration?, status?}`; invalid `status` → 400
- `POST /api/tasks/parse` — `{text, space_hint?}` → AI parse (may create several tasks; single object returned when one, array when several). ChangeLog actor = 'ai'
- `PUT /api/tasks/<id>` — any subset of fields; `status` and `completed` kept in sync (status wins)
- `DELETE /api/tasks/<id>`
- `POST /api/tasks/<id>/toggle-freeze`
- `POST /api/tasks/freeze-day` — `{date: YYYY-MM-DD}` toggles freeze for all tasks scheduled that day
- `POST /api/tasks/reorder` — `{task_ids: [...]}` rewrites priorities from list order

### Scheduling (`src/routes/schedule.py`)
- `POST /api/schedule` — auto-schedules all incomplete, non-frozen tasks into 30-min slots around external events, frozen tasks, and per-space time constraints
- `GET /api/logs?limit=` — ChangeLog entries, newest first

### Spaces (`src/routes/spaces.py`)
- `GET/POST /api/spaces`, `PUT/DELETE /api/spaces/<id>` — CRUD, audited

### Notes (`src/routes/notes.py`)
- `GET /api/notes?space_id=` — DTOs ordered by updated_at desc
- `POST /api/notes` — `{space_id (required), title?, content_markdown?}`
- `GET/PUT/DELETE /api/notes/<id>`
- `POST /api/notes/<id>/cleanify` — → `{content}`; does NOT persist (the editor applies it and the debounced PUT autosave persists). Degrades to the original content on AI failure
- `POST /api/notes/<id>/promote-to-task` — `{selected_text}` → task draft DTOs (space defaulting to the note's); persists nothing

### Mail (`src/routes/mailboxes.py`)
- `GET /api/mailboxes` — DTOs with `has_password`, never the password
- `POST /api/mailboxes` — `{label, host, port?, username, password, use_ssl?, space_id?}` (password encrypted at rest)
- `PUT /api/mailboxes/<id>` — any subset; password only replaced when a non-empty one is sent
- `DELETE /api/mailboxes/<id>`
- `GET /api/mailboxes/<id>/messages?limit=` — live IMAP fetch → `[{uid, subject, from, date, snippet, unread}]`; 502 on IMAP failure, 409 when the stored password can't be decrypted (SECRET_KEY rotated)
- `GET /api/mailboxes/<id>/messages/<uid>` — one message including its full plain-text `body` (read-only fetch, never marks it seen); 404 unknown uid, same 502/409 mapping
- `POST /api/mailboxes/<id>/messages/<uid>/add-task` — fetches the body, runs the email-to-task AI prompt, returns draft(s) pre-tagged with the mailbox's `space_id`; persists nothing

### Calendar sources (`src/routes/calendar_sources.py`)
- `GET/POST /api/calendar-sources`, `DELETE /api/calendar-sources/<id>`
- `GET /api/external-events` — live ICS fetch from all enabled sources (30-day window)

## Frontend Architecture

### The unified shell (`templates/index.html` + `static/js/app.js`)

One page, one header:

- **Header**: brand · nav tabs (Tasks/Notes/Mail/Calendar, in `1/2/3/4` order) · global quick-capture input (AI task creation from anywhere) · action icons (auto-schedule, spaces, calendars, shortcuts help, logout).
- **Destinations** are sections toggled client-side (no page reloads), deep-linkable via `#tasks / #notes / #mail / #calendar`; the last destination is remembered (`localStorage`).
- **Tasks**: kanban board (SortableJS across columns → `PUT {status}`; intra-column order is priority/deadline — dedicated ordinal deferred per PrePRD), space filter chips (persisted), per-column "+" inline create (Enter creates in that column/space; input stays open for rapid entry), Done column capped at 30 most recently finished (`completed_at` desc). Board ⇄ Overview toggle persisted; the Overview has a persisted "Show done" toggle listing finished tasks most-recently-finished first.
- **Calendar**: preserved behavior — FullCalendar with drag = reschedule + auto-freeze (Ctrl skips freeze), resize = duration change, sidebar task list with drag-to-reorder.
- **Notes** (`notes.js`, `NotesView` module, lazy init): EasyMDE source editor with the full formatting toolbar (headings, lists, table, preview/side-by-side/fullscreen…) plus the custom add-task/Cleanify/Undo actions, deferred persistence (no empty "Untitled" rows), debounced autosave, Cleanify + single-step Undo, promote-selection-to-task.
- **Mail** (`mail.js`, `MailView` module, lazy init): mailbox sidebar + add/edit modal, live inbox list, click a message → reader modal (full plain-text body, still read-only server-side), right-click (or Task button) → AI draft → shared confirm modal.
- **`task_draft_modal.js`**: the shared "confirm this AI task draft" modal used by both promote-to-task and email-to-task (drafts are never silently persisted).

### Keyboard shortcuts (one coherent set — see the in-app `?` help modal)

| Shortcut | Action |
|---|---|
| `1` / `2` / `3` / `4` | Switch to Tasks / Notes / Mail / Calendar |
| `/` | Focus the quick-capture input |
| `Ctrl+Enter` | Create task with AI (in any capture input) |
| `S` | Auto-schedule all |
| `?` | Shortcuts help |
| Click / `Ctrl`+Click / `Shift`+Click on any task | Edit / toggle done / toggle freeze (same convention on the board, the list, the overview, and calendar events) |
| `Ctrl`+Click a calendar day header | Freeze/unfreeze the whole day |
| Drag a board card | Change its status |
| Drag/resize a calendar event | Reschedule (+freeze; hold `Ctrl` to skip freeze) |

## AI Integration

Provider abstraction in `ai_parser.py`: `OpenAIProvider` (any OpenAI-compatible endpoint, raw `requests`) and `AnthropicProvider`, selected by `get_ai_provider()` from `AI_API_BASE_URL`. Three entry points share it:

| Entry point | Prompt file | Post-processing | Degradation |
|---|---|---|---|
| `parse_task_with_ai` | `src/prompt.md` (+ spaces context) | JSON → task dicts, relative deadlines normalized | trivial title/description draft |
| `cleanify_note_with_ai` | `src/prompts/notes_cleanify.md` (+ note's Space context) | raw text | original note returned unchanged |
| `email_to_task_with_ai` | `src/prompts/email_to_task.md` (+ spaces context) | reuses `parse_task` seam | subject/body-derived draft |

There is deliberately **no** `AIProvider.complete()` generalization — `cleanify` is a sibling method and email-to-task reuses `parse_task` (see `.opencode/context/topics/ai-parsing.md`).

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| AI_API_KEY | for AI features | None | LLM API key |
| AI_API_BASE_URL | No | `https://api.openai.com/v1/` | Any OpenAI-compatible endpoint, or `api.anthropic.com` |
| AI_MODEL | No | `gpt-3.5-turbo` | Model name |
| APP_PASSWORD | Yes | "admin" | Single shared password |
| SECRET_KEY | Yes | dev fallback | Flask session secret **and** the key mailbox passwords are encrypted with — rotating it forces re-entering mailbox passwords |
| FLASK_ENV | No | development | |

## Database migrations

`migrate_db.py` (repo root) is the supported migration path — no Alembic. It:

1. **CREATEs missing tables** and **ADDs missing columns** (additive-only diff of `db.metadata` vs the SQLite file; never drops anything).
2. Runs **idempotent data fixups**: backfills `tasks.space_id` from the legacy `tasks.space` name, `tasks.status='done'` from `completed=1`, and `tasks.completed_at` from `updated_at` for already-done tasks.

```bash
python migrate_db.py --dry-run          # print the plan
python migrate_db.py --yes              # apply
python migrate_db.py --db path/to/tasks.db
```

Run it after pulling code that changes `models.py`, before `docker compose up`.

## Testing

`pytest` (52 tests): route-layer integration tests through the Flask test client with an in-memory SQLite (`tests/conftest.py`), a `StubAIProvider` patched at the `get_ai_provider` seam, the IMAP seam patched with canned messages, and a pure-data scheduler suite (`tests/test_scheduler.py`) that needs no DB.

```bash
python -m pytest -q
```

## Deployment

```bash
docker-compose up -d        # port 53000, ./instance holds tasks.db
```

Production notes: change `APP_PASSWORD`, generate a random `SECRET_KEY` (remember: it also encrypts mailbox passwords), use a WSGI server, HTTPS, and back up `instance/tasks.db`.

## Version History

**2026-07 — Unified workspace (PrePRD 000)**:
- ✅ Backend modularized: app factory + per-domain blueprints, audited-write seam (ChangeLog actor), scheduler pure-over-data, space_id migration finished
- ✅ Task.status kanban workflow (todo/doing/blocked/done) with completed sync
- ✅ Unified shell: one header, four destinations, global quick capture, coherent shortcuts + help modal
- ✅ Kanban board home with space chips + inline create; Overview kept as secondary subview
- ✅ Notes merged into the shell (deep-linked at /#notes)
- ✅ Mail module: space-linked IMAP mailboxes (encrypted passwords), live inbox, email→task drafts
- ✅ migrate_db.py: data fixups + ADD COLUMN fix

**2025-12 → 2026-06**:
- ✅ Notes module (CRUD, EasyMDE, Cleanify + Undo, promote-to-task) + pytest harness
- ✅ Generic multi-provider AI API (OpenAI-compatible + Anthropic)
- ✅ Space ID foreign keys, multi-task AI parsing, task freezing, external ICS calendars, auto-scheduling, change logging, Docker deploy

---

**Last Updated**: 2026-07-01
**Documentation Version**: 2.0
