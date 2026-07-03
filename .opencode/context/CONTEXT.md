# Project Context

> Lean always-on overview. Deep material lives in `topics/` (loaded on demand via the `@` refs below) and the roadmap lives in `.opencode/plans/`. Rules live in `AGENTS.md`. Keep this file lean enough to load every session, but long enough to convey the project's overall context — a fresh agent reading only this file should grasp what the project is, how it's shaped, and the key domain terms.

- **Product**: Simpler — a self-hosted, **unified ADHD-friendly workspace**: tasks (kanban home), calendar (AI auto-scheduling), notes (markdown capture + Cleanify), and mail (IMAP → task), all organized around the same **Space** concept and served from one shell with one header. Guiding principle: friction-free, everything reachable in as few clicks as possible.
- **Actors**: Single user (ADHD individual) authenticated by one shared `APP_PASSWORD`. External integrators: any OpenAI-compatible LLM API (Anthropic / Mistral / OpenAI / Infomaniak) for task parsing / note cleaning / email-to-task, any ICS-publishing calendar (Google, Outlook) for external events, and any IMAP server for mailboxes.
- **Tech stack**: Python 3.11, Flask 3 (app factory + per-domain blueprints) + Flask-SQLAlchemy + SQLite (`instance/tasks.db`), `cryptography` (Fernet) for mailbox secrets, Bootstrap 5 + FullCalendar.js + SortableJS + EasyMDE (vanilla JS, CDN, no build step), Docker Compose deploy on port 53000. `migrate_db.py` (repo root) migrates prod DBs (additive DDL + idempotent data fixups). Active vision: `.opencode/plans/000_PrePRD_unified-adhd-workspace.md` (applied 2026-07).

## Architecture

Single-process Flask server. `src/app.py` is an **app factory only**; routes live in per-domain blueprints under `src/routes/`. Frontend is **one unified shell** (`templates/index.html`): one header (destination nav + global AI quick-capture + actions), five client-side-switched destinations (Tasks / Notes / Mail / Calendar / Spaces, in that `1/2/3/4/5` order) deep-linkable via URL hash. Data flows:

- **Capture → task**: header quick-capture (or per-space modal) → `POST /api/tasks/parse` → `parse_task_with_ai` (LLM returns one-or-more task JSON, relative deadlines normalized) → tasks persisted (`status='todo'`, ChangeLog `actor='ai'`). Every AI task prompt is assembled in `prompt_context.py`: base prompt + spaces list + **space guidance block** (per-space `context_markdown`, framed guide-not-source).
- **Board**: `GET /api/tasks?include_completed=true` → kanban columns by `status`; drag between columns → `PUT {status}`; per-column inline create → `POST /api/tasks {status}`. Kanban inline-create (`+` in a column header → Enter) routes through `/api/tasks/parse` with `force_status` (column placement) + `restrict_space` (active board space filter, hard single-space prompt scope); same AI parsing as header quick-capture. The `board-card-priority` badge is click-to-edit inline (arrows nudge, Enter commits clamped 0–10).
- **Schedule**: `POST /api/schedule` → `schedule_tasks` (pure-over-data: `to_schedulable()` dicts + space-id-keyed constraints) places non-frozen incomplete tasks into 30-min slots around live-fetched ICS events + frozen tasks. Optional `task_ids` body scopes placement to those tasks (others keep their slots, treated as frozen); the kanban board sends its displayed Doing tasks, other views schedule everything.
- **Notes**: capture → debounced autosave (deferred persistence) → optional Cleanify (LLM tidy, undo) → optional promote-selection-to-task (draft → shared confirm modal → `POST /api/tasks`).
- **Mail**: registered mailbox (password Fernet-encrypted at rest) → live IMAP fetch per open → click message = reader modal (full body, never marked read) / right-click = email-to-task draft pre-tagged with the mailbox's Space → confirm modal → `POST /api/tasks`.
- **Audit**: every mutation goes through `audit.record_change()` — one transaction per mutation, `actor` column ('user'/'ai').

Module map:
- `src/app.py` — app factory (`create_app`), blueprint registration, `db.create_all` + seeding.
- `src/routes/` — `pages` (/, /notes→/#notes, login), `tasks`, `spaces`, `notes`, `mailboxes`, `calendar_sources` (+ external-events), `schedule` (+ logs).
- `src/models.py` — `Task` (with `status` + `apply_status`/`apply_completed`), `Space`, `ChangeLog` (with `actor`), `Note`, `Mailbox`, `CalendarSource`.
- `src/audit.py` — `record_change()`: the single audited-write seam.
- `src/auth.py` / `src/datetime_utils.py` / `src/prompt_context.py` / `src/seeding.py` — extracted cross-cutting helpers (login_required, parse_iso_datetime, AI prompt assembly incl. `space_guidance_block()`, default spaces shared with tests).
- `src/scheduler.py` — pure-over-data auto-scheduling; `to_schedulable()` adapter at the seam.
- `src/ai_parser.py` — `AIProvider` base + `OpenAIProvider`/`AnthropicProvider`; entry points `parse_task_with_ai`, `cleanify_note_with_ai`, `email_to_task_with_ai` (all gracefully degrading); `get_ai_provider` URL-heuristic factory.
- `src/calendar_integration.py` — live ICS fetch. `src/mail_integration.py` — live IMAP fetch (transient DTOs). `src/crypto_utils.py` — Fernet from SECRET_KEY.
- `src/config.py` — env + prompt loading, cached at startup: `SYSTEM_PROMPT` (`task_creation.md`), `NOTES_CLEANIFY_PROMPT`, `EMAIL_TO_TASK_PROMPT` (all under `src/prompts/*.md`).
- `src/templates/index.html` — THE shell (all destinations + modals incl. shortcuts help). `login.html`.
- `src/static/js/` — `app.js` (shell nav, shortcuts, board, calendar, overview), `notes.js` (`NotesView`), `mail.js` (`MailView`), `spaces.js` (`SpacesView` — space CRUD + AI context editor), `task_draft_modal.js` (shared draft confirm).
- `tests/` — pytest harness (in-memory SQLite, `StubAIProvider`, patched IMAP seam) + route-layer integration tests + pure-data scheduler suite. 57 tests.
- `migrate_db.py` — prod-DB migrations (see data-model topic).
- `doc/` — `PROJECT_DESCRIPTION.md` (full schema + API ref, the authoritative spec), `README.md`, `TODO.md`, `payment_plan_possibilities.md`.

### Deep dives (loaded on demand — read with the Read tool when the task touches them)
- @.opencode/context/topics/data-model.md
- @.opencode/context/topics/scheduling.md
- @.opencode/context/topics/ai-parsing.md
- @.opencode/context/topics/notes.md
- @.opencode/context/topics/mail.md

## Domain glossary

- **Task**: unit with title, priority (0-10, higher=more urgent), deadline, estimated_duration (minutes), scheduled_start/end, `status` (`todo/doing/blocked/done`), completed, completed_at, frozen flags.
- **Status ⇔ completed invariant**: `status` is the single source of truth for done-ness; `completed` is kept in sync (`done` ⇔ True) for the calendar UI and legacy callers. `completed_at` is stamped on the first transition into done, kept on re-saves, cleared on leaving done. `frozen` is orthogonal.
- **Space**: a named context (e.g. `work`, `study`, `association`) carrying JSON `time_constraints` (per-weekday windows) constraining when its tasks may be scheduled, plus a user-editable `context_markdown`. The shared spine: tasks, notes, and mailboxes all link to a Space by `space_id`. Managed in the Spaces destination (press `5`).
- **Space AI context**: `Space.context_markdown` is appended to every AI task prompt (`space_guidance_block()`) wrapped in explicit guide-not-source framing — it steers space choice/priority/deadline/wording but must never be copied into task fields or treated as part of the user's request.
- **space_id vs space**: `Task.space_id` (FK) is canonical; the `Task.space` string column is legacy, unread by code, and backfilled into `space_id` by `migrate_db.py`. `to_dict()` echoes the name from the relation.
- **Unified shell**: one page (`index.html`), one header, destinations switched client-side (`switchDestination`), deep links `#tasks/#notes/#mail/#calendar/#spaces`, last destination remembered.
- **Board / Overview**: the two Tasks subviews — kanban (primary) and grouped-by-space overview (secondary); toggle persisted. The Overview's "Show done" toggle (persisted) lists finished tasks by `completed_at` desc.
- **Shortcuts convention**: `1/2/3/4/5` destinations (Tasks/Notes/Mail/Calendar/Spaces), `/` quick capture, `S` schedule, `?` help; on any task representation click=edit, Ctrl+click=done, Shift+click=freeze; in Mail click=open reader, right-click=email→task. **Board card exception**: a plain click on a board card's `board-card-priority` badge edits the priority inline (number input; arrows nudge, Enter commits clamped 0–10, Esc/blur reverts) instead of opening the edit modal — `stopPropagation`-guarded so it never triggers the modal nor the Alt multi-select path. The badge editor is board-only; the Overview `space-task-priority` stays non-interactive.
- **Board multi-select**: in the kanban subview only, Alt+click toggles a card in/out of a global selection set (across all columns); dragging a selected card moves every selected task to the target column (only the dragged card animates, others re-render on success); Enter forces all selected to done; Ctrl+C copies the set as `- **Title**: description` markdown bullets (description dropped when empty). Selection clears on Esc, empty-board click, plain/Ctrl/Shift click on a card (which then runs its normal action), destination/subview switch, and after every batch action (drop/Enter/Ctrl+C).
- **Shortcuts help modal = single source of truth**: the `#helpModal` table in `templates/index.html` lists every keyboard shortcut shown to the user. **Always update this table when adding, removing, or changing any shortcut** — keep it in sync with `initKeyboardShortcuts()` and the click/press handlers in `src/static/js/app.js` (and the per-view JS files). The shortcuts convention entries above describe the behaviour; the help table is what the user sees.
- **Time constraints**: JSON list of `{"day": 0-6, "start": "HH:MM", "end": "HH:MM"}` on a `Space`; day 0=Monday.
- **Frozen task / frozen day**: pinned so the auto-scheduler won't move it; still consumes a busy slot.
- **Auto-schedule**: `POST /api/schedule` → `schedule_tasks()` places non-frozen tasks into 30-min slots by `-priority, deadline, created_at`, avoiding external + frozen + placed slots; deadline is a hard search bound (unmeetable deadline ⇒ left unscheduled).
- **External events**: ICS entries pulled live from `CalendarSource.ics_url`; hard busy slots.
- **ChangeLog**: audit row (`create/update/delete/reorder/freeze/unfreeze`) with full old/new JSON snapshots and `actor` ('user'/'ai') for tasks, spaces, notes, mailboxes — written only via `audit.record_change()`; training data for future preference learning.
- **AI provider abstraction**: `AIProvider` + `OpenAIProvider` (any OpenAI-compatible endpoint) / `AnthropicProvider`, chosen by URL heuristic. Sibling methods `parse_task` and `cleanify` — deliberately NOT unified into `complete()`. Email-to-task reuses `parse_task`.
- **Note**: Space-scoped markdown capture; deferred persistence (no row until non-empty), debounced autosave, list by `updated_at` desc.
- **Cleanify**: LLM tidy of a note into a structured form (`# Title`, note date in italics below it, `##` subtitles, bold key points, `-` bullets), returned without persisting; applied in-editor, persists via normal autosave; single-step Undo; degrades to original on failure. The note's `created_at` date is passed in the system prompt.
- **Promote-to-task / Email-to-task**: AI-drafted tasks that are NEVER silently persisted — the user confirms in the shared `TaskDraftModal`, `POST /api/tasks` commits.
- **Mailbox**: registered IMAP account linked to a Space; password Fernet-encrypted at rest (key from SECRET_KEY), never returned by any API; inbox fetched live, nothing persisted.
- **APP_PASSWORD**: the single shared password gating `/login`; no user account model.

## Conventions pointer

- Rules (style, commands, gotchas): `AGENTS.md` (managed by `/init` — none exists yet in this repo).
- Roadmap (PRDs, issues): `.opencode/plans/` — `000_PrePRD_unified-adhd-workspace.md` is the applied vision (2026-07); archives in `plans/archive/` + `plans/issues/archive/`. `doc/TODO.md` holds the remaining item-level roadmap.
- This overview: you are here (managed by `/refresh-context-md`).

## Current focus

PrePRD `000` (Unified ADHD-Friendly Workspace) is **implemented** (2026-07): backend modularization per the 2026-06-30 architecture review (blueprints, audited-write seam, pure-data scheduler, space_id migration finished), `Task.status` kanban workflow, the unified one-header shell with kanban home + coherent shortcuts + help modal, Notes merged into the shell, and the Mail module (encrypted IMAP mailboxes, live inbox, email-to-task). `migrate_db.py` carries the schema + data migrations for prod.

Remaining next-up items (per `doc/TODO.md`): (1) global user config (breaks, default work times) — the scheduler now has a clean seam to read it from; (2) green-hosting badge; (3) click/drag on calendar to create a task; (4) shift+drag to reserve a timespan for a space; (5) intra-column kanban ordinal if priority-ordering feels wrong in practice (PrePRD out-of-scope 6); (6) investigate "not all tasks planned" — `tests/test_scheduler.py` is the regression net to extend. Grilling pass on the PrePRD still recommended before further large steps (see its Further Notes).
