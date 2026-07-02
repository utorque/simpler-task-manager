# Simpler — Unified ADHD-Friendly Workspace

A simple, fast, self-hosted workspace designed for people with ADHD: **tasks, calendar, notes, and mail in one page**, organized around shared *Spaces*, with AI-powered capture everywhere and automatic scheduling. One header, four destinations, everything a keystroke away.

## Features

### The unified shell
- **One main header** with the destination nav (Tasks / Notes / Mail / Calendar / Spaces), a **global quick-capture input** (AI task creation from any view), and action buttons (auto-schedule, calendars, shortcuts help, logout)
- **View switching without page reloads**: press `1` (Tasks) / `2` (Notes) / `3` (Mail) / `4` (Calendar) / `5` (Spaces), or click the tabs; deep links via `/#tasks`, `/#notes`, `/#mail`, `/#calendar`, `/#spaces`; the app reopens where you left it
- **Coherent shortcuts everywhere** — press `?` in the app for the full list

### Tasks (home) — kanban board
- Four columns: **To do / Doing / Blocked / Done**; drag a card between columns to change its status (dragging into Done completes it)
- **Space filter chips** on top — click a space to focus the whole board on it (remembered across sessions)
- **Inline create** per column: `+` opens an input, `Enter` creates the task directly in that column (and in the filtered space); the input stays open for rapid entry
- Compact cards: title, priority badge, space, deadline, duration, frozen indicator; the Done column shows the 30 most recently finished
- The **Overview** subview (grouped-by-space dashboard with stats) is one toggle away and remembered; its **Show done** toggle lists finished tasks most-recently-finished first

### Calendar
- **AI-Powered Task Creation**: paste text (emails, notes, etc.) into the header input; the LLM extracts title, description, space, priority (0-10), deadline, and duration — multiple tasks from one paste when the text clearly contains several
- **Smart Scheduling**: `Auto-Schedule` (or press `S`) places tasks in 30-minute slots by priority and deadline, respecting per-space time windows, external calendar events, and frozen tasks
- **Task Freezing**: `Shift+Click` a task/event (or `Ctrl+Click` a day header for the whole day) to pin it so auto-schedule won't move it; dragging an event freezes it automatically (hold `Ctrl` while dropping to skip)
- **External Calendar Integration**: Google Calendar, Outlook, or any ICS URL — fetched live, shown alongside your tasks, treated as busy time
- **Everything is a gesture**: drag to reschedule, resize to change duration, `Ctrl+Click` to complete, click to edit

### Notes
- Space-scoped markdown notes (EasyMDE with the standard formatting toolbar — headings, lists, quote, code, links, preview, side-by-side) with **debounced autosave** and deferred persistence (no empty "Untitled" leftovers)
- **Cleanify**: one click runs the messy note through the LLM and tidies it in place — with a persistent one-step Undo
- **Promote to task**: select any text in a note → one click → AI drafts a task (pre-filled with the note's space) → confirm before it's saved

### Mail
- Register any number of **IMAP mailboxes**, each linked to a Space
- **Passwords encrypted at rest** (Fernet, key derived from `SECRET_KEY`) and never returned by the API or shown in the UI again
- Browse the inbox **live** (nothing is stored, messages stay unread) and **click any email to read it** — the full body opens in a reader, still without marking it read on the server
- **Right-click an email → task** (also from the reader): the LLM derives the actual ask from the email, pre-tagged with the mailbox's Space; you confirm before anything is saved

### Spaces
- Full space management as its own destination (press `5`): name, description, per-weekday **time windows** (constrain auto-scheduling), and…
- **AI context** — a free markdown field per space. Whatever you write there (current projects, people, what counts as urgent, conventions) is fed to the LLM alongside the system prompt on **every** AI task creation (quick capture, note promotion, email-to-task). It is explicitly framed as a *guide, not a source*: it steers space choice, priority, deadline, and wording, but is never copied into your tasks

### Cross-cutting
- **Spaces**: shared contexts (work / study / association / …); tasks, notes, and mailboxes all attach to them
- **Change Logging**: every create/update/delete is audited with full before/after snapshots and an actor tag (user vs AI) — future fuel for preference learning
- **Single shared password** (`APP_PASSWORD`) gates everything; no accounts to manage

## Quick Start with Docker

### Prerequisites
- Docker and Docker Compose
- An API key for any OpenAI-compatible LLM endpoint (OpenAI, Mistral, Infomaniak…) or Anthropic (for the AI features)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd simpler-smart-calendar
```

2. Create a `.env` file:
```bash
cp .env.example .env
```

3. Edit `.env` (see `.env.example` for all options):
```env
SECRET_KEY=your_random_secret_key_here
APP_PASSWORD=your_secure_password_here
FLASK_ENV=production
AI_API_KEY=your_llm_api_key
AI_API_BASE_URL=https://api.openai.com/v1/
AI_MODEL=gpt-3.5-turbo
```

4. Start the application:
```bash
docker-compose up -d
```

5. Access the application at `http://localhost:53000`

### Upgrading an existing installation

After pulling new code, migrate your database before restarting (additive-only, idempotent, never drops data):

```bash
python migrate_db.py --dry-run   # show what would change
python migrate_db.py --yes       # apply schema diff + data backfills
```

## Manual Installation

### Prerequisites
- Python 3.11 or higher

### Setup

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # then edit it
python src/app.py                   # http://localhost:53000
```

## Configuration

### Environment Variables

| Variable | Description |
|---|---|
| `AI_API_KEY` | API key for your LLM provider (powers task parsing, Cleanify, and email-to-task) |
| `AI_API_BASE_URL` | Any OpenAI-compatible endpoint, or `https://api.anthropic.com/` for Anthropic (auto-selected) |
| `AI_MODEL` | e.g. `gpt-3.5-turbo`, `mistral-small`, `claude-haiku-4-5` |
| `APP_PASSWORD` | The single shared password gating the app |
| `SECRET_KEY` | Flask session secret — **also encrypts mailbox passwords**; rotating it means re-entering them |
| `FLASK_ENV` | `development` or `production` |

### Prompts

The three AI system prompts are plain markdown files, loaded once at startup — edit and restart to customize:
- `src/prompts/task_creation.md` — task parsing (the JSON formatting contract)
- `src/prompts/notes_cleanify.md` — note tidying
- `src/prompts/email_to_task.md` — email-to-task extraction

Per-space **AI context** (edited live in the Spaces view, no restart needed) is appended to the task-drafting prompts automatically.

### Default Spaces

Seeded on first run (editable in the UI): **work** (Mon-Fri 9-17), **study** (unconstrained), **association** (Wed 18-22).

## API

See [PROJECT_DESCRIPTION.md](PROJECT_DESCRIPTION.md) for the full schema and endpoint reference (tasks, parse, schedule, spaces, notes, cleanify, promote-to-task, mailboxes, messages, email-to-task, calendar sources, logs).

## Development

### Running Tests

```bash
python -m pytest -q     # 57 route-layer + scheduler tests
```

### Building Docker Image
```bash
docker build -t simpler-workspace .
```

### Contributions
Contributions are welcome! Please feel free to submit issues and pull requests. Agent/contributor context lives in `.opencode/context/`.

## Roadmap

See [TODO.md](TODO.md). Highlights: global user config (breaks, default work times), calendar click/drag-to-create, timespan reservation per space, audio capture, markdown rendering for notes, habit learning from the change log.

## License

[LICENSE](../LICENSE)

## Credits

Built with ADHD users in mind — designed to be as simple and fast as possible to reduce friction in task management.
