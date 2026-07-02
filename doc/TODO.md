# TODOS

## NEXT TODO
- [ ] global user config (breaks, breaks after tasks, work times for everything). Update the db accordingly. (The `migrate.py` half of this item shipped as `migrate_db.py` — additive schema diff + data fixups against the prod SQLite db; the scheduler is now pure-over-data so it has a clean seam to read a UserConfig from.)
- [ ] add green hosting label -> <img src="https://app.greenweb.org/api/v3/greencheckimage/simpler.utorque.ch?nocache=true" alt="This website runs on green hosting - verified by thegreenwebfoundation.org" width="200px" height="95px">
- [ ] clic/dragclic calendar to create a task (paste text as the rest) — partially subsumed by the kanban per-column inline create; the calendar-surface gesture itself is still open
- [ ] shift+drag on the calendar to reserve timespan for a space
- [ ] advanced task creator modal — partially subsumed: AI quick capture is global (header), kanban columns have inline direct-create, and AI drafts (promote-to-task / email-to-task) open a confirm-before-save modal. Still open: a full manual form creator with AI-recreate (ctrl-enter) from the capture input
- [ ] kanban intra-column ordering: currently priority/deadline-derived; add a dedicated `kanban_order` ordinal if it feels wrong in practice (PrePRD 000 out-of-scope 6)

## GOOD FEATURES
- [ ] fully redo the UI to be nicer, more responsive, softer to the eye while prioritizing UX- Potentially change the stack ?
- [ ] button to reschedule only for current filter
- [ ] add audio task using infomaniak whisper api
- [ ] add telegram bot with n8n
- [ ] ctrl shift click on the task list to remove it
- [ ] mail: unread-only filter, multiple folders (INBOX only today) — message reader shipped 2026-07 (click a row → modal)
- [ ] notes: markdown rendering / live preview (source-only by design today)

- [ ] do some marketing planning to redo the ui and sell points (swiss made, environmentally friendly ai with infomaniak, opensource models with mistral, fair usage-based pricing instead of subscription)

## PLANNED
- [ ] investigate not all tasks planned when many tasked ? (scheduler is now pure-over-data with a test suite — `tests/test_scheduler.py` — so this can get a failing regression test first; note: an unmeetable deadline leaves a task unscheduled by design)
- [ ] add list view to calendar

## MAYBE LATER
- [ ] task button add context and re-plan
- [ ] button to automatically do docker-compose pull and docker-compose up -d from the web app (supersecure lol)
- [ ] get all tasks for context or something ?
- [ ] add learn user habits (ChangeLog now records `actor` user/ai — useful signal)
- [ ] optimize system prompt

## MEH
- [ ] actual full personal organizer with pages that allow to save links of personal stuff, your home page, linked with spaces. idea : main page to see the amount of tasks and all basic links to get started
- [ ] subspaces & subtaskd

## DONE
- [x] 2026-07 shell polish: nav order Tasks/Notes/Mail/Calendar = 1/2/3/4; mail reader (click an email → full body, still never marked read); Overview "Show done" toggle ordered by new `tasks.completed_at` (backfilled by migrate_db.py); full EasyMDE toolbar restored
- [x] 2026-07 unified workspace (PrePRD 000): one shell, one header, Tasks kanban home (todo/doing/blocked/done + space filter chips + inline create), Calendar demoted to sibling destination (behavior preserved), Notes merged into the shell, Mail module (encrypted IMAP mailboxes, live inbox, email→task)
- [x] help modal to see all shortcuts (press `?`; shortcuts made coherent: 1/2/3/4 destinations, / capture, S schedule, click/Ctrl/Shift conventions)
- [x] direct filter on task list to see only X or Y places (space chips on the board)
- [x] Add "Overall view" with a global dashboard (Overview subview under Tasks)
- [x] way to see tasks finished / add a done button or sth (Done column on the board; Ctrl+click anywhere)
- [x] migrate.py that works against the prod SQLite db (`migrate_db.py`: additive DDL + idempotent data fixups: space_id backfill, status backfill)
- [x] backend modularization (architecture review 2026-06-30 candidates 1-4: blueprints + app factory, audited-write seam with actor column, scheduler off the ORM with tests, space_id migration finished)
- [x] LOOKS FIXED ? add the current date and time to the planner so it does not plan things for too early
- [x] redo ai api to be generic / use mistral or cheaper & less energy intensive models ; infomaniak api looks cheap (mistral 24b instruct) ; I suppose use openai python interface with api url and apikey as env variables.
- [x] add space id and not name directly to change name lol
- [x] Make AI return list of tasks instead of just one necessarily
- [x] Drag task edge on calendar to change time
- [x] ctrl click to mark task done
- [x] lock/freeze tasks on modification in the calendar (ctrl click or sth)
