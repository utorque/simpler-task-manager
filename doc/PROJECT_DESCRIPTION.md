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

An **Assistant destination** (6th tab, shortcut `6`) embeds a first-party [Chainlit](https://chainlit.io) chat app (`chat/`, mounted same-origin at `/assistant` by `asgi.py`): persistent chat history, model picker, slash commands that inject tasks/notes into the context, a space-filter subheader, per-space AI guidance injection, file uploads, web search, skills, and an agentic tool loop pre-wired to the `mcp_server/` sidecar (audited workspace tools) and to the `sandbox/` execution sidecar (isolated code execution over a shared file workspace, produced files returned to the user). Setup: `doc/setup-assistant.md`.

**Primary Use**: Self-hosted personal task management
**Target Users**: Individuals with ADHD who need simple, fast organization with minimal context switching

## Technology Stack

### Backend
- **Framework**: Flask 3 (app factory + per-domain blueprints)
- **Database**: SQLite with Flask-SQLAlchemy
- **AI**: any OpenAI-compatible endpoint (OpenAI, Mistral, Infomaniak, …) or the Anthropic API — selected at runtime from `AI_API_BASE_URL`
- **Auth**: single shared `APP_PASSWORD`, session cookie; optional `API_TOKEN` bearer header for machine clients (the MCP sidecar)
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
├── mcp_server/                # simpler-mcp sidecar: FastMCP tools wrapping the REST API (PRD 002)
│   ├── server.py              # ~26 typed agent tools (tasks/spaces/notes/mail-read/schedule/changelog)
│   ├── Dockerfile / requirements.txt / README.md
├── src/
│   ├── app.py                 # App factory only; registers blueprints
│   ├── models.py              # Task, Space, ChangeLog, Note, Mailbox, CalendarSource
│   ├── routes/                # Per-domain blueprints
│   │   ├── pages.py           # /, /notes (deep link), /n/<token> (public note), /login, /logout
│   │   ├── tasks.py           # /api/tasks* (CRUD, parse, freeze, reorder)
│   │   ├── spaces.py          # /api/spaces*
│   │   ├── notes.py           # /api/notes* (CRUD, cleanify, promote-to-task, public share)
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
│   ├── prompts/               # AI system prompts (task_creation, notes_cleanify, email_to_task, task_selection)
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
| priority | FLOAT | DEFAULT 0 | Priority 0-10, higher = more urgent; UI edits use integers, drag-reorder stores fractional values (existing INTEGER-declared prod column keeps REALs via SQLite type affinity) |
| deadline | DATETIME | NULLABLE | Task deadline (ISO format) |
| estimated_duration | INTEGER | NULLABLE | Duration in minutes (default 60) |
| scheduled_start / scheduled_end | DATETIME | NULLABLE | Set by the auto-scheduler |
| status | STRING(20) | NOT NULL DEFAULT 'todo' | Kanban state: todo / doing / blocked / done |
| completed | BOOLEAN | DEFAULT FALSE | Kept in sync: completed ⇔ status == 'done' |
| completed_at | DATETIME | NULLABLE | Stamped on the first transition into done; cleared when leaving done; preserved on re-saves of a done task |
| frozen | BOOLEAN | DEFAULT FALSE | Prevents auto-rescheduling (orthogonal to status) |
| note_id | INTEGER | NULLABLE FK notes.id | Provenance: the note this task was promoted from (one-way link). Nulled by the note delete route (SQLite runs without PRAGMA foreign_keys, so the FK's SET NULL is enforced in ORM code) |
| created_at / updated_at | DATETIME | | utcnow / onupdate utcnow |

**Status/completed invariant**: `status` is the single source of truth for done-ness. Writing `status='done'` flips `completed=True`; any other status flips it back. Legacy callers writing `completed` get `status` derived (`done`, or `todo` when un-completing). When both are sent, `status` wins.

`to_dict()` echoes `space` (the name) denormalized from the `space_rel` relation — `space_id` is canonical, and embeds the full `subtasks` list.

### `subtasks`
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PRIMARY KEY | |
| task_id | INTEGER | NOT NULL FK tasks.id ON DELETE CASCADE | Parent task |
| title | STRING(500) | NOT NULL | The only content field — subtasks are checklist items, not tasks (no priority/deadline/duration/scheduling) |
| done | BOOLEAN | NOT NULL DEFAULT FALSE | |
| position | INTEGER | NOT NULL DEFAULT 0 | Creation order |
| created_at | DATETIME | | |

**Two-way status sync** (`Task.sync_status_from_subtasks` + `apply_status`): checking the last open subtask marks the task `done`; unchecking a subtask of a done task pulls it back to `doing`; adding an open subtask to a done task also reopens it to `doing`; manually marking the task done auto-checks every subtask. Tasks without subtasks are untouched. Subtask mutations are audited as `update` ChangeLog rows on the **parent task**.

### `spaces`
`id`, `name` (unique), `description` (helps the AI infer context), `context_markdown` (user-editable AI guidance — see AI Integration), `time_constraints` (JSON string), `created_at`.

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
`id`, `space_id` (FK, **NOT NULL**), `title` (nullable — the list UI falls back to "Untitled"), `content_markdown` (raw markdown source), `created_at` / `updated_at`. `to_dict()` also exposes `public_share_token` (the token of the note's public share, or `null` when unshared).

### `note_shares`
`id`, `note_id` (FK, **NOT NULL**, **UNIQUE** — at most one share per note), `token` (**UNIQUE**, random `secrets.token_urlsafe(16)`), `created_at`. A row is the note's single public read-only credential: anyone holding `/n/<token>` can view the note. "Stop sharing" **deletes** the row (the token is revoked, never reused; re-sharing mints a fresh one). Deleting the note cascades the share away (ORM `delete-orphan`).

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

All `/api/*` routes require the session cookie (`@login_required`, JSON 401 otherwise) — or, when the optional `API_TOKEN` env var is set, an `Authorization: Bearer <API_TOKEN>` header (constant-time compare; used by the `mcp_server/` sidecar). Bearer-authenticated mutations are audited with ChangeLog `actor='agent'` (via `g.actor`; routes passing an explicit actor — the AI parse paths' `'ai'` — keep it).

### Authentication
- `POST /login` — `{password}` → sets session
- `POST /logout`

### Tasks (`src/routes/tasks.py`)
- `GET /api/tasks?include_completed=true|false` — ordered by priority desc, deadline asc
- `POST /api/tasks` — `{title, description?, space_id?, priority?, deadline?, estimated_duration?, status?, subtasks?, note_id?}`; `subtasks` is a list of title strings (or `{title, done?}` dicts); `note_id` links the task to its source note; an empty `title` borrows the note's title at creation time — and when the note is still untitled the task may be created title-less (backfilled on note save); empty title with no note → 400; invalid `status`/unknown `note_id` → 400
- `POST /api/tasks/parse` — `{text, space_hint?}` → AI parse. The prompt always yields ONE task; listed items/steps in the input become its `subtasks`. ChangeLog actor = 'ai'
- `PUT /api/tasks/<id>` — any subset of fields; `status` and `completed` kept in sync (status wins); `status='done'` auto-checks all subtasks
- `DELETE /api/tasks/<id>` — cascades to subtasks
- `POST /api/tasks/<id>/subtasks` — `{title}` adds one subtask as-is (no AI); reopens a done parent to `doing`
- `PUT /api/subtasks/<id>` — `{done?, title?}`; runs the two-way status sync; returns the full parent task
- `DELETE /api/subtasks/<id>` — returns the full parent task (deleting the last open subtask can complete it)
- `POST /api/tasks/<id>/toggle-freeze`
- `POST /api/tasks/freeze-day` — `{date: YYYY-MM-DD}` toggles freeze for all tasks scheduled that day
- `POST /api/tasks/reorder` — `{task_id, priority}` nudges ONLY the dragged task's priority (fractional values allowed, clamped 0-10); manual drag-reorder never rewrites the rest of the list
- `POST /api/tasks/auto-doing` — `{text, space_ids?}` AI-selects the TODO tasks matching the stated intent (candidates optionally restricted to `space_ids`) and moves them to `doing` (ChangeLog actor = 'ai'); → `{moved: [...]}`; 502 when the AI response is unavailable/unparseable

### Scheduling (`src/routes/schedule.py`)
- `POST /api/schedule` — auto-schedules all incomplete, non-frozen tasks into 30-min slots around external events, frozen tasks, and per-space time constraints
- `GET /api/logs?limit=` — ChangeLog entries, newest first

### Spaces (`src/routes/spaces.py`)
- `GET/POST /api/spaces`, `PUT/DELETE /api/spaces/<id>` — CRUD, audited; fields incl. `context_markdown` (AI guidance) and `time_constraints`

### Notes (`src/routes/notes.py`)
- `GET /api/notes?space_id=` — DTOs ordered by updated_at desc; `space_id` may repeat (`?space_id=1&space_id=3`) to get the union of several spaces; absent = all
- `POST /api/notes` — `{space_id (required), title?, content_markdown?}`
- `GET/PUT/DELETE /api/notes/<id>` — PUT re-runs the title backfill on every save: linked tasks (`note_id`) whose title is still empty take the note's title; DELETE detaches linked tasks (`note_id → NULL`)
- `POST /api/notes/<id>/cleanify` — → `{content}`; does NOT persist (the editor applies it and the debounced PUT autosave persists). Degrades to the original content on AI failure
- `POST /api/notes/<id>/promote-to-task` — `{selected_text}` → task draft DTOs (space defaulting to the note's, `note_id` provenance tag, empty AI title borrows the note's); persists nothing
- `POST /api/notes/<id>/share` — create (or return the existing) public read-only share → `{token}`; idempotent (an already-shared note keeps its token); audited (`action='share'`). The client builds the URL as `<origin>/n/<token>`
- `DELETE /api/notes/<id>/share` — revoke the public share → 204; idempotent; audited (`action='unshare'`)
- `GET /n/<token>` — **public, no auth** (the token is the credential). Server-rendered on every request, so it always shows the note's latest saved markdown, mounted in a read-only EasyMDE locked to preview mode with a "copy raw markdown" toolbar tool. An unknown/revoked token 404s (`noindex`)

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

- **Header**: brand · nav tabs (Tasks/Notes/Mail/Calendar/Spaces, in `1/2/3/4/5` order) · global quick-capture input (AI task creation from anywhere) · action icons (auto-schedule, calendars, shortcuts help, logout).
- **Destinations** are sections toggled client-side (no page reloads), deep-linkable via `#tasks / #notes / #mail / #calendar / #spaces`; the last destination is remembered (`localStorage`).
- **Tasks**: kanban board (SortableJS: cross-column drag → `PUT {status}` only; same-column drag = manual reorder nudging just the dragged task's priority via `POST /api/tasks/reorder`; Done stays completion-time ordered, no intra-column sort there; modifier+mousedown never starts a drag — Shift/Ctrl/Alt clicks stay clicks even with hand jitter, so a sloppy Shift+click can't drop the card into a neighbouring column), space filter chips (persisted; click = one space, Ctrl+click = toggle several spaces into the filter, Alt+click = exclude a space — greyed-out chip, its tasks hidden until Alt+clicked again; "All spaces" resets both), per-column "+" inline create (Enter creates in that column; `restrict_space` only sent when exactly one space is visible), Doing column's magic button → "what do you want to do?" modal → `POST /api/tasks/auto-doing` moves the AI-matched to-dos into Doing, Done column capped at 30 most recently finished (`completed_at` desc). Board ⇄ Overview toggle persisted; the Overview has a persisted "Show done" toggle listing finished tasks most-recently-finished first.
- **Calendar**: preserved behavior — FullCalendar with drag = reschedule + auto-freeze (Ctrl skips freeze), resize = duration change, sidebar task list with drag-to-reorder (same single-task priority nudge as the board).
- **Notes** (`notes.js`, `NotesView` module, lazy init): space chips like the board (click = one space, Ctrl+click = multi-space view, Alt+click = exclude a space — greyed chip, its notes hidden; rows show a space tag when several spaces are visible; new notes land in the first visible selected space), EasyMDE source editor with the standard formatting toolbar (headings, lists, quote, code, link/image, preview, side-by-side — table and fullscreen deliberately omitted; side-by-side stays inside the notes layout via `sideBySideFullscreen: false`) plus the custom add-task/Cleanify/Undo actions and a **copy-raw-markdown** toolbar tool (copies the note's markdown source — present on both the private editor and the public share page). Existing notes open **rendered (preview mode)** — clicking the preview switches to edit mode; new/empty notes open straight in edit mode. Deferred persistence (no empty "Untitled" rows), debounced autosave (Ctrl+Enter flushes it immediately), Cleanify + single-step Undo, promote-selection-to-task. **Public sharing**: a Share button (next to Download in the notes toolbar, enabled once a note is open) POSTs `/api/notes/<id>/share`, then copies `<origin>/n/<token>` to the clipboard and flips to "Copy link"; a Stop-sharing button appears to revoke it. The `/n/<token>` page is a standalone server-rendered template (`public_note.html`) mounting a read-only, preview-locked EasyMDE that always reflects the note's latest saved markdown.
- **Spaces** (`spaces.js`, `SpacesView` module, lazy init): space list + editor — name, description, **AI context markdown** (guidance injected into every AI task prompt), and per-weekday time windows. Replaces the old header-button modal.
- **Mail** (`mail.js`, `MailView` module, lazy init): mailbox sidebar + add/edit modal, live inbox list, click a message → reader modal (full plain-text body, still read-only server-side), right-click (or Task button) → AI draft → shared confirm modal.
- **`task_draft_modal.js`**: the shared "confirm this AI task draft" modal used by both promote-to-task and email-to-task (drafts are never silently persisted).

### Keyboard shortcuts (one coherent set — see the in-app `?` help modal)

| Shortcut | Action |
|---|---|
| `1` / `2` / `3` / `4` / `5` | Switch to Tasks / Notes / Mail / Calendar / Spaces |
| `6` | Switch to Assistant (AI chat; only when the Chainlit app is mounted, i.e. the `asgi.py` entrypoint) |
| `/` | Focus the quick-capture input |
| `Ctrl+Enter` | Save from wherever you're typing (open modal's primary action, notes autosave flush, space editor save; capture inputs create the task) |
| `S` | Auto-schedule all |
| `?` | Shortcuts help |
| Click / `Ctrl`+Click / `Shift`+Click on any task | Edit / toggle done / toggle freeze (same convention on the list, the overview, and calendar events) |
| `Shift`+Click a board card | Advance the status: To do → Doing, Doing ⇄ Blocked, Done → Doing (board-only exception to the freeze convention) |
| `Ctrl`+Click a calendar day header | Freeze/unfreeze the whole day |
| Drag a board card to another column | Change its status |
| Drag a board card within its column | Reorder it (nudges only that task's priority) |
| `Ctrl`+Click a space chip (board/Notes) | Add/remove the space to the filter (multi-space view) |
| `Alt`+Click a space chip (board/Notes) | Exclude the space: greyed-out chip, its tasks/notes hidden (`Alt`+Click again or "All" to restore) |
| Click a note in the list | Open it rendered (preview mode); click the preview to edit |
| Drag/resize a calendar event | Reschedule (+freeze; hold `Ctrl` to skip freeze) |

## AI Integration

Provider abstraction in `ai_parser.py`: `OpenAIProvider` (any OpenAI-compatible endpoint, raw `requests`) and `AnthropicProvider`, selected by `get_ai_provider()` from `AI_API_BASE_URL`. Three entry points share it:

| Entry point | Prompt file | Post-processing | Degradation |
|---|---|---|---|
| `parse_task_with_ai` | `src/prompts/task_creation.md` (+ spaces context) | JSON → task dicts, relative deadlines normalized. Prompt mandates a SINGLE task; listed items become `subtasks` (list of strings) | trivial title/description draft |
| `cleanify_note_with_ai` | `src/prompts/notes_cleanify.md` (+ note's Space context) | raw text | original note returned unchanged |
| `email_to_task_with_ai` | `src/prompts/email_to_task.md` (+ spaces context) | reuses `parse_task` seam | subject/body-derived draft |
| `select_tasks_with_ai` | `src/prompts/task_selection.md` | reuses `cleanify` seam (raw completion); JSON id array normalized to candidate subset | returns `None` → route responds 502 |

There is deliberately **no** `AIProvider.complete()` generalization — `cleanify` is a sibling method and email-to-task reuses `parse_task` (see `.opencode/context/topics/ai-parsing.md`).

**Space guidance**: every task-drafting prompt additionally carries the per-space **AI context markdown** (`Space.context_markdown`, edited in the Spaces destination), assembled by `prompt_context.space_guidance_block()`. It is wrapped in explicit guide-not-source framing: the model uses it to choose the space and set priority/deadline/duration/wording, but must never copy it into task fields or derive tasks from it. Spaces without context contribute nothing (prompts stay identical to before).

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| AI_API_KEY | for AI features | None | LLM API key |
| AI_API_BASE_URL | No | `https://api.openai.com/v1/` | Any OpenAI-compatible endpoint, or `api.anthropic.com` |
| AI_MODEL | No | `gpt-3.5-turbo` | Model name |
| APP_PASSWORD | Yes | "admin" | Single shared password |
| API_TOKEN | No | None | Bearer token for machine clients (MCP sidecar + embedded assistant); unset = bearer auth off and the assistant loses workspace access |
| CHAT_MODELS | No | AI_MODEL | Comma-separated model ids offered in the assistant's model picker (first = default) |
| SIMPLER_MCP_URL | No | None | Simpler's MCP sidecar, pre-integrated as assistant tools (compose sets `http://mcp:8765/mcp`) |
| SANDBOX_MCP_URL | No | None | Execution-sandbox MCP sidecar (compose sets `http://sandbox:8766/mcp`) |
| CHAT_FILES_DIR | No | instance/assistant_files | Assistant file workspace (compose points it at the volume shared with the sandbox) |
| SECRET_KEY | Yes | dev fallback | Flask session secret **and** the key mailbox passwords are encrypted with — rotating it forces re-entering mailbox passwords |
| FLASK_ENV | No | development | |

## Database migrations

`migrate_db.py` (repo root) is the supported migration path — no Alembic. Standalone (stdlib-only: `sqlite3` + `shutil`), so it can be copied to the server and run without the app's dependencies. It:

1. **Backs up** the DB first (`tasks.db.bak-<timestamp>` alongside the file).
2. Applies the **additive schema diff**: CREATE missing tables + indexes, ALTER TABLE ADD COLUMN for columns present in `SCHEMA` but absent from the file. Never drops anything.
3. Runs **idempotent data fixups** (`DATA_FIXUPS`): guarded UPDATEs backfilling new/canonical columns from legacy ones (`tasks.space_id` from the legacy `space` name, `tasks.status` from `completed`, `tasks.completed_at` from `updated_at`, `change_logs.actor`). Each only touches rows where the target is still unset.
4. **Verifies** the final schema and fails loudly (backup untouched) if anything is still missing.

```bash
python3 migrate_db.py --dry-run             # print the plan, write nothing
python3 migrate_db.py --yes                 # apply without the confirmation prompt
python3 migrate_db.py --db path/to/tasks.db # default: ./instance/tasks.db
```

**Run it after pulling code that changes `models.py`, before `docker compose up`** — nothing in the Dockerfile or compose file migrates automatically. `db.create_all()` (called at app startup) creates missing *tables* only; it will **never** add a column to a table that already exists, so a schema change without this script surfaces as a runtime `no such column: …` 500.

The script's `SCHEMA` is a hand-written mirror of `src/models.py` — the price of staying dependency-free. `tests/test_migrate_db.py` is the drift guard: it fails if a model table/column has no counterpart in `SCHEMA` (or vice versa), and end-to-end-migrates a pre-kanban DB shape. When you add a column that needs a backfill, add the `SCHEMA` entry **and** a guarded UPDATE to `DATA_FIXUPS` in the same change.

## Testing

`pytest` (322 tests): route-layer integration tests through the Flask test client with an in-memory SQLite (`tests/conftest.py`), a `StubAIProvider` patched at the `get_ai_provider` seam, the IMAP seam patched with canned messages, and a pure-data scheduler suite (`tests/test_scheduler.py`) that needs no DB. The MCP sidecar's tools are tested in-process (`tests/test_mcp_tools.py`): its httpx client is swapped for an `httpx.WSGITransport` pointed at the Flask test app, so every tool exercises the real routes through the bearer-token path (`tests/test_api_token_auth.py` covers the auth seam itself).

```bash
python -m pytest -q
```

## Deployment

```bash
docker-compose up -d        # port 53000, ./instance holds tasks.db
```

Production notes: change `APP_PASSWORD`, generate a random `SECRET_KEY` (remember: it also encrypts mailbox passwords), use a WSGI server, HTTPS, and back up `instance/tasks.db`.

**Embedded assistant (built in)**: the compose file also runs `mcp` (the MCP sidecar, streamable HTTP at `/mcp`, compose-network-only) and `sandbox` (the assistant's isolated execution sidecar, internal network + shared `/workspace` volume). The Chainlit assistant itself runs inside the `web` container (`asgi.py` mounts it same-origin at `/assistant`), gated by the normal login via a session-cookie auth bridge. Set `API_TOKEN` (`openssl rand -hex 32`) to give it workspace access — **walkthrough: `doc/setup-assistant.md`**.

## Version History

**2026-07 — chat history: `steps.modes` write failure**:
- ✅ Fixed `sqlite3.ProgrammingError: Error binding parameter 4: type 'dict' is not supported` — Chainlit 2.11's mode selector attaches a `modes` dict to every user_message, and upstream json.dumps()es only `metadata` / `generation`, so the raw dict was bound to our TEXT column. The write raised inside the persistence path, so chat kept working while **every user message was silently lost from the history DB**
- ✅ `chat/data_layer.py`: the `tags` shim generalized to `JSON_TEXT_FIELDS = ('tags', 'modes')` — the list of Postgres-native columns upstream does not serialize itself; empty dicts left alone so upstream's ON CONFLICT column-omission still protects stored values. `modes` added to `STEPS_ADDITIVE_COLUMNS` for DBs created before it joined the schema

**2026-07 — migrate_db.py restored to a schema reconciler**:
- ✅ Fixed `no such column: tasks.status` on DBs predating the kanban workflow: the earlier rewrite of `migrate_db.py` into a hand-listed two-step script had dropped the `status` / `completed_at` / `actor` migrations and every data fixup, leaving no supported way forward for an existing DB
- ✅ Back to a full additive reconciler (declarative `SCHEMA` mirroring `models.py` + `DATA_FIXUPS` + post-run verification), still stdlib-only; `--dry-run` / `--yes` / `--db` flags restored to match the documented usage
- ✅ `tests/test_migrate_db.py` drift guard: fails when `models.py` and `SCHEMA` disagree in either direction, so a migration can no longer be silently lost
- ✅ `Subtask.task_id` marked `index=True` so fresh DBs get `ix_subtasks_task_id` too (previously only migrated DBs had it)

**2026-07 — Embedded Chainlit assistant (replaces the Hermes integration)**:
- ✅ First-party Chainlit app (`chat/`) mounted same-origin at `/assistant` by the new `asgi.py` entrypoint (FastAPI umbrella: Chainlit ASGI + Flask via a2wsgi); Hermes webui container + `/hermes-ui/` proxy removed
- ✅ One login: Chainlit header-auth validates the Flask session cookie by signature (`chat/auth_bridge.py`); chat history persists in `instance/chainlit.db` (SQLAlchemy data layer, SQLite)
- ✅ Model picker (chat profiles from `CHAT_MODELS`), streaming provider adapter for OpenAI-compatible + Anthropic endpoints incl. tool calls (`chat/providers.py`)
- ✅ Workspace integration: starters from tasks in Doing, `/task` `/note` `/tasks` `/notes` `/skill` slash commands injecting entities as persisted context (a task always brings its linked note), space-filter subheader synced into the chat session, per-space guidance in the system prompt
- ✅ Agentic tool loop (`chat/agent.py` + `chat/toolbox.py`): pre-integrated MCP servers (`mcp_server` sidecar + `sandbox` sidecar), user-added MCP servers via Chainlit's UI, native web_search/fetch_url, skills (`chat/skills/`), file uploads in / produced files back out
- ✅ `sandbox/` sidecar: FastMCP execution sandbox (run_python/run_shell/file tools) in its own container, internal-only network, shared `/workspace` volume; CI publishes `-sandbox` image; local E2E harness in `scripts/e2e/`

**2026-07 — Hermes agent integration (PRD 002, since replaced — see above)**:
- ✅ `API_TOKEN` bearer auth mode in `auth.py` (constant-time compare; off when unset) + `actor='agent'` ChangeLog attribution via `g.actor` default in `audit.record_change()`
- ✅ `mcp_server/` FastMCP sidecar (streamable HTTP :8765) — ~26 typed tools wrapping the REST API (tasks/subtasks/spaces/notes/schedule/freeze/changelog/mail-read/email-to-task drafts), compose service `mcp`
- ✅ Hermes destination: optional 6th tab (shortcut `6`, `#hermes`) embedding hermes-webui via lazy iframe; hidden when unconfigured; help modal updated
- ✅ Fully containerized: `hermes-webui` compose service (chat UI + agent, auto-installed into `./hermes-home`, no host port) + `/hermes-ui/` same-origin login-gated streaming proxy (`routes/hermes_proxy.py`) so the embed needs zero reverse-proxy changes; setup walkthrough in `doc/setup-hermes-integration.md`

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

**Last Updated**: 2026-07-05
**Documentation Version**: 2.0
