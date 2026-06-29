# Project Context

> Lean always-on overview. Deep material lives in `topics/` (loaded on demand via the `@` refs below) and the roadmap lives in `.opencode/plans/`. Rules live in `AGENTS.md`. Keep this file lean enough to load every session, but long enough to convey the project's overall context — a fresh agent reading only this file should grasp what the project is, how it's shaped, and the key domain terms.

- **Product**: Simpler Smart Calendar — a self-hosted, ADHD-friendly task manager that turns pasted natural-language text into tasks and auto-schedules them on a calendar by priority, deadline, and per-context time constraints.
- **Actors**: Single user (ADHD individual) authenticated by one shared `APP_PASSWORD`. External integrators: any OpenAI-compatible LLM API (Anthropic / Mistral / OpenAI / Infomaniak) for task parsing, and any ICS-publishing calendar (Google, Outlook) for external events.
- **Tech stack**: Python 3.11, Flask 3 + Flask-SQLAlchemy + Flask-Login, SQLite (`instance/tasks.db`), Bootstrap 5 + FullCalendar.js + SortableJS (vanilla JS frontend), Docker Compose deploy on port 53000 (mapped). No `.opencode/plans/` PRDs exist yet — the active roadmap lives in `doc/TODO.md`.

## Architecture

Single-process Flask server (`src/app.py`) serving both the JSON API and the server-rendered templates. Data flow: user pastes text → `POST /api/tasks/parse` calls `ai_parser.parse_task_with_ai` (LLM returns one-or-more task JSON, relative deadlines normalized to absolute) → task(s) persisted via SQLAlchemy → `POST /api/schedule` runs `scheduler.schedule_tasks` over non-frozen tasks against external ICS events + per-space time constraints → calendar UI reflects `scheduled_start/end`. External calendar events are fetched live on each `/api/external-events` call from registered `calendar_sources` (no background sync). Auth is session-cookie based on a single shared password (no user table).

Module map:
- `src/app.py` — Flask app, route handlers, auth decorator, datetime parsing (~16k chars).
- `src/models.py` — SQLAlchemy models: `Task`, `Space`, `ChangeLog`, `CalendarSource` (+ `to_dict` serializers).
- `src/scheduler.py` — auto-scheduling algorithm: 30-min slot grid, priority+deadline sort, space time-constraint awareness, frozen-task/external-event avoidance.
- `src/ai_parser.py` — generic `AIProvider` base + `OpenAIProvider` / `AnthropicProvider` impls; `parse_task_with_ai` factory, response JSON extraction and relative-date normalization.
- `src/calendar_integration.py` — `fetch_external_events`: GET ICS URL, parse with `icalendar`, return naive-datetime event dicts for next 30 days.
- `src/config.py` — `Config` class: reads `.env` (SECRET_KEY, AI_API_KEY/BASE_URL/MODEL, APP_PASSWORD), loads `prompt.md` as `SYSTEM_PROMPT`.
- `src/prompt.md` — system prompt for the LLM task-parsing call (formatting contract for returned JSON).
- `src/templates/` — `index.html` (main UI), `login.html`.
- `src/static/` — `css/style.css`, `js/app.js` (drag-drop, freeze, calendar wiring).
- `doc/` — `README.md` (setup/usage), `PROJECT_DESCRIPTION.md` (full schema + API ref, the authoritative spec), `TODO.md` (roadmap), `payment_plan_possibilities.md`.
- `Dockerfile` / `docker-compose.yml` — container build and port 53000 + `./instance` volume mount.

### Deep dives (loaded on demand — read with the Read tool when the task touches them)
- @.opencode/context/topics/data-model.md
- @.opencode/context/topics/scheduling.md
- @.opencode/context/topics/ai-parsing.md

## Domain glossary

- **Task**: scheduled unit with title, priority (0-10, higher=more urgent), deadline, estimated_duration (minutes), scheduled_start/end, completed, frozen flags.
- **Space**: a named context (e.g. `work`, `study`, `association`) carrying JSON `time_constraints` (per-weekday time windows) that constrain when its tasks may be scheduled.
- **space_id vs space**: `Task.space_id` (FK → spaces.id) is the current relation; `Task.space` (string name) is DEPRECATED, kept only for backward-compat migration — new code must use `space_id`.
- **Time constraints**: JSON list of `{"day": 0-6, "start": "HH:MM", "end": "HH:MM"}` on a `Space`; day 0=Monday … 6=Sunday.
- **Frozen task / frozen day**: `Task.frozen=True` (or ctrl+clicking a day header) pins the task/day so the auto-scheduler will not move it; frozen tasks still consume a busy slot.
- **Auto-schedule**: `POST /api/schedule` → `schedule_tasks()` places non-frozen tasks into 30-min-aligned slots, ordering by `-priority` then `deadline` then `created_at`, avoiding external + frozen + already-scheduled busy slots.
- **External events**: calendar entries pulled from a registered `CalendarSource.ics_url` via `fetch_external_events`; treated as hard busy slots during scheduling.
- **ChangeLog**: audit row (`create/update/delete/reorder/freeze`) recording old/new JSON for tasks and spaces — intended as training data for future preference learning.
- **AI provider abstraction**: `AIProvider` base with `OpenAIProvider` (works for any OpenAI-compatible endpoint incl. Mistral/Infomaniak) and `AnthropicProvider`; selected at request time by URL/model heuristics in `get_ai_provider`.
- **APP_PASSWORD**: the single shared password gating `/login`; there is no user account model.

## Conventions pointer

- Rules (style, commands, gotchas): `AGENTS.md` (managed by `/init` — none exists yet in this repo).
- Roadmap (PRDs, issues): `.opencode/plans/` (empty — managed by `/plan`, `to-prd`, `to-issues`). Until PRDs exist, `doc/TODO.md` is the de-facto roadmap.
- This overview: you are here (managed by `/refresh-context-md`).

## Current focus

No PRDs in `.opencode/plans/`. Per `doc/TODO.md`, the active next-up items are: (1) global user config (breaks, breaks-after-tasks, default work times) with a `migrate.py` that works against the prod SQLite db; (2) green-hosting badge; (3) click/drag on calendar to create a task; (4) shift+drag to reserve a timespan for a space; (5) an "advanced task creator" modal. Larger explorations: a full UI/stack rewrite and a marketing plan (Swiss-made, green AI via Infomaniak, open models, usage-based pricing). Recently shipped: generic multi-provider AI API, space_id migration, multi-task AI parsing, freeze/lock.
