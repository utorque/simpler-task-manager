# Simpler — Unified ADHD-Friendly Workspace

A self-hosted workspace that unifies **tasks, calendar, notes, and mail** around shared *Spaces* — with AI-powered capture everywhere and automatic scheduling. Built for ADHD workflows: one page, one header, everything reachable in as few clicks (or keystrokes) as possible.

- **Tasks** — kanban board home (`todo / doing / blocked / done`), space filter chips, drag between columns, inline create; grouped-by-space overview (with a show-done toggle, most recently finished first) as the secondary view
- **Notes** — space-scoped markdown capture (full EasyMDE toolbar) with AI "Cleanify" and promote-selection-to-task
- **Mail** — register IMAP inboxes (passwords encrypted at rest), browse live, click to read, right-click an email → AI-drafted task
- **Calendar** — AI-parsed tasks auto-scheduled around your external ICS calendars and per-space time windows; drag to reschedule (and freeze)
- **Spaces** — manage your contexts (work / study / …) with per-weekday scheduling windows and a per-space **AI context markdown** that guides every AI task creation (guide, not source — never copied into tasks)
- **Quick capture** — paste anything into the header input from any view; the LLM turns it into structured tasks
- Keyboard-first: `1/2/3/4/5` switch views (Tasks/Notes/Mail/Calendar/Spaces), `/` focuses capture, `?` shows all shortcuts

## Project Structure

```
.
├── src/              # Flask app (app factory + routes/ blueprints), templates, static JS/CSS
├── tests/            # pytest suite (57 tests)
├── migrate_db.py     # prod SQLite migration script (additive DDL + data fixups)
├── doc/              # Documentation
│   ├── README.md     # Detailed setup & usage documentation
│   ├── PROJECT_DESCRIPTION.md  # Authoritative spec (schema, API, architecture)
│   └── TODO.md       # Roadmap
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Quick Start

See [doc/README.md](doc/README.md) for detailed documentation and setup instructions.

### Using Docker

```bash
docker-compose up
```

### Local Development

```bash
pip install -r requirements.txt
python src/app.py          # http://localhost:53000
python -m pytest -q        # run the test suite
```

### Upgrading an existing database

After pulling code that changes the schema, run the migration script against your prod SQLite file before restarting:

```bash
python migrate_db.py --dry-run   # show the plan
python migrate_db.py --yes       # apply (additive-only + idempotent backfills)
```

## Documentation

All project documentation is located in the [doc/](doc/) directory:
- [README.md](doc/README.md) - Main documentation
- [PROJECT_DESCRIPTION.md](doc/PROJECT_DESCRIPTION.md) - Authoritative spec (schema, API, features)
- [TODO.md](doc/TODO.md) - Development roadmap

Agent/contributor context lives in `.opencode/context/` (overview + deep-dive topics).

## License

See [LICENSE](LICENSE) for details.
