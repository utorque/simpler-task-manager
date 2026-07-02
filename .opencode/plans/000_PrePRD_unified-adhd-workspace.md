# PrePRD: Unified ADHD-Friendly Workspace

- **ID**: 000
- **Type**: PrePRD (draft-stage product vision; intentionally pre-alignment — not yet grilled)
- **Status**: Draft
- **File**: `000_PrePRD_unified-adhd-workspace.md`
- **Authored**: 2026-06-29

> Note on the `PrePRD` label: the user explicitly requested this artifact be named a "PrePRD" rather than a `PRD`, signalling that the vision is captured but **not yet grilled for alignment**. Treat the contents below as a one-shot synthesis of the user's stated intent, grounded in the current codebase. It is the input to a future `grilling` pass, not the output of one. Per the `to-prd` lifecycle, `Status` stays `Draft` until the user signs off.

> **Implementation note (2026-07-01)**: the user asked for this vision to be applied directly (no issue decomposition). It shipped on branch `claude/project-vision-modularization-3nbvhk` in five commits: (1) backend modularization per the 2026-06-30 architecture review, (2) `Task.status` workflow + `migrate_db.py` backfills, (3) the unified one-header shell (kanban home, coherent shortcuts, Notes merged in — one deviation from decision A: destinations are client-side-switched views inside one shell rather than server-rendered routes, per the user's explicit "one main header, switch from a view to another" instruction; deep links preserved via URL hashes), (4) the Mail module, (5) docs/context updates. Deferred as written here: per-task `kanban_order` ordinal (out-of-scope 6). The recommended grilling pass remains open.

---

## Problem Statement

Today this product is a *calendar* that happens to manage tasks: the calendar is the front door, task entry is pasted-text → AI parse → schedule, and everything else (notes, mail) lives in separate tools (OneNote, a mail client). In practice the user barely opens the calendar. What they actually want is a single, friction-free surface where tasks, notes, and email live together, organized around the same "space" concept, reachable in as few clicks as possible, and friendly to an ADHD workflow (visual, drag-droppable, low-context-switching).

Concretely, today's friction:

1. The calendar is the home view, but the user doesn't use it — so the front door of the product leads somewhere they don't want to go.
2. Tasks have only `completed` / `frozen` flags — there is no notion of "doing" vs "blocked" vs "todo". The user cannot see work-in-progress at a glance; they can only see done-or-not-done.
3. Notes live in OneNote, outside the product's space model. Context about a space (work, study, association) is scattered across tools.
4. Mail lives in a separate client. Turning an email into a task means copy-paste back into the calendar app — exactly the multi-tool, multi-click friction the product is supposed to eliminate.
5. The AI plumbing (provider abstraction, prompt loading) is wired only for task parsing. The same LLM call pattern could power "clean up my messy notes" and "turn this email into a task", but it isn't generalized.

## Solution

Evolve the product from "a smart calendar" into **a unified, ADHD-friendly workspace** organized around **Spaces**, with four top-level destinations reachable from a single nav:

1. **Tasks** (the new home) — a kanban board as the primary view (`todo` / `doing` / `blocked` / `done`), plus the existing grouped-by-space overview kept as a secondary view. Drag-and-drop between columns, inline create in any column, and a space filter row on top to focus on one space.
2. **Calendar** — kept exactly as-is today, demoted from "home" to one of four siblings.
3. **Notes** — a OneNote-like markdown note editor (no rendering for now), organized by Space, with a "Cleanify" button that runs the messy note through the LLM and returns a cleaner version.
4. **Mail** — register any number of mailboxes, link each mailbox to a Space, browse the mailbox's emails, and right-click an email → "Add task" which auto-creates a task from the email's content using the AI parser, with the space inferred from the mailbox's link.

Common spine: every new entity (note, mailbox, email-derived task) is attached to a **Space**, so the same `work / study / association` grouping flows across tasks, notes, and mail. The AI provider abstraction is generalized from "parse a task" to "complete an arbitrary system-prompted call" so that task-parsing, note-cleaning, and email-to-task reuse one provider and one auth config.

**Guiding principle (stated by the user):** heavily streamlined, friction-free, all-in-one-place, ADHD-friendly — everything reachable in as few clicks as possible.

---

## User Stories

### Cross-cutting / navigation

1. As the user, I want a top-level nav with Tasks / Calendar / Notes / Mail, so that I can jump between the four workspaces without page reloads or context switches.
2. As the user, I want Tasks to be the default landing destination (not Calendar), so that the app opens where I actually work.
3. As the user, I want every new entity (task, note, mailbox) to belong to a Space, so that work/study/association stays consistent across all four surfaces.
4. As the user, I want the existing calendar and all its current behavior (drag-drop, freeze, external ICS, auto-schedule) to remain unchanged, so that this evolution is purely additive for the calendar surface.
5. As the user, I want to create or switch Spaces from anywhere in the app, so that I don't have to navigate back to a settings page to file something under a new space.
6. As the user, I want the single shared `APP_PASSWORD` to keep gating everything, so that I don't manage per-feature auth.

### Tasks — kanban view (the new core)

7. As the user, I want a kanban view with four columns — `todo`, `doing`, `blocked`, `done` — so that I can see the state of my work-in-progress at a glance.
8. As the user, I want to drag a task card from one column to another, so that updating a task's status is a single gesture, not a form.
9. As the user, I want to drag tasks vertically within a column to reorder them, so that the most important thing in each column is on top.
10. As the user, I want to create a task directly inside a column (a "+" affordance or an inline input), so that the new task is born already in the right status without an extra step.
11. As the user, I want a space filter row at the top of the kanban, so that I can click a Space chip and see only that Space's tasks across all four columns.
12. As the user, I want a "All spaces" / unfiltered state on the same filter row, so that I can see cross-space work at once.
13. As the user, I want a task card to show its title, priority, deadline, and space badge, so that I have enough context without opening the card.
14. As the user, I want clicking a task card to open the existing task editor, so that I can edit full details when the kanban card isn't enough.
15. As the user, I want the existing pasted-text → AI parse → create-task flow to remain available (as the "advanced creator"), so that the friction-free way to capture a task from arbitrary text still exists.
16. As the user, I want dragging a task into `done` to mark it `completed=True` (and vice-versa for moving it back out), so that the existing completion semantics stay consistent with the new status field.
17. As the user, I want the kanban to preserve a task's `frozen` / scheduled state, so that moving a task on the kanban doesn't silently break the calendar's auto-schedule view of it.
18. As an ADHD user, I want the kanban columns to be visually distinct and the cards to be compact, so that I can visually scan without cognitive overload.

### Tasks — grouped-by-space view (kept as-is)

19. As the user, I want to toggle between the new kanban view and the existing grouped-by-space overview, so that I don't lose the way I currently see tasks.
20. As the user, I want the toggle to remember my last choice across sessions, so that the app opens where I left it.

### Calendar

21. As the user, I want the Calendar destination to be byte-for-byte the current calendar (FullCalendar, drag-drop, freeze, external ICS sources, auto-schedule), so that the calendar experience is preserved exactly.
22. As the user, I want calendar operations (drag a scheduled task, freeze a day, toggle completed visibility) to keep working after the IA change, so that the demotion from "home" to "one of four" is purely navigational.

### Notes

23. As the user, I want a Notes destination that opens a list of notes for the currently-selected Space, so that notes are organized the same way tasks are.
24. As the user, I want to create a new note in a Space with a single click, so that capturing a thought is friction-free.
25. As the user, I want to switch which Space's notes I'm viewing from the Notes page (same space-switch affordance as Tasks), so that I move between spaces without leaving Notes.
26. As the user, I want the note editor to be a plain markdown **source** editor (no live rendering required for this phase), so that I can write notes fast without a rendering layer that isn't built yet.
27. As the user, I want notes to auto-save as I type (debounced), so that I never lose a thought to a missed save.
28. As the user, I want a "Cleanify" button on each note, so that I can turn my messy, stream-of-consciousness notes into something cleaner with one click.
29. As the user, I want the Cleanify result to replace the editor content (with an undo affordance), so that I keep the cleaned version unless I explicitly revert.
30. As the user, I want to delete a note, so that stale notes don't accumulate.
31. As the user, I want to rename / retitle a note, so that the note list stays navigable.
32. As the user, I want notes to show a last-edited timestamp in the list, so that I can find the note I was just working on.

### Mail

33. As the user, I want a Mail destination where I can register any number of mailboxes (IMAP host, port, username, password, TLS/SSL flags), so that all my inboxes are reachable from one place.
34. As the user, I want to link each registered mailbox to exactly one Space, so that emails from a mailbox are automatically associated with the right space.
35. As the user, I want mailbox credentials stored encrypted at rest (not plaintext in the DB), so that a leaked `tasks.db` doesn't leak my email passwords.
36. As the user, I want to browse a mailbox's inbox (subject, sender, date, read/unread, preview) inside the Mail page, so that I can triage mail without leaving the product.
37. As the user, I want to right-click an email in the list and choose "Add task", so that turning mail into a task is a single gesture.
38. As the user, I want the "Add task" action to auto-create a task whose content is derived (by the AI parser) from the email body, whose Space is the mailbox's linked Space, and whose title/description are pre-filled for me to confirm, so that the path from "email received" to "task on the kanban" is as short as possible.
39. As the user, I want the created task to open in the task editor before being saved, so that I can correct the AI before committing.
40. As the user, I want to delete a registered mailbox, so that I can revoke access cleanly.
41. As the user, I want to edit a registered mailbox's link to a different Space, so that re-organization is cheap.
42. As the user, I want mailbox passwords never to appear in plaintext in the UI after entry, so that over-the-shoulder snooping isn't trivial.

### AI / LLM plumbing (cross-feature)

43. As the user, I want the same AI provider config (`AI_API_KEY` / `AI_API_BASE_URL` / `AI_MODEL`) to power task parsing, note cleaning, and email-to-task, so that I configure the LLM once.
44. As the user, I want note "Cleanify" to use a dedicated prompt (a "clean up messy markdown notes" system prompt), so that the LLM's behavior matches the task.
45. As the user, I want email-to-task to use a dedicated prompt that knows it's deriving a task from an email, so that the resulting task's title/description/deadline estimation reflect the email's actual ask.
46. As the user, I want every AI call (parse, cleanify, email-to-task) to degrade gracefully when the AI is unreachable or returns nothing usable, so that one integration being down doesn't brick the others.

### Audit / ChangeLog

47. As the user, I want note create/update/delete to be recorded in `ChangeLog`, so that the existing audit pattern extends to the new entity type.
48. As the user, I want mailbox create/delete and email-to-task creation to be recorded in `ChangeLog`, so that the audit trail covers the new mail surface.

---

## Implementation Decisions

The decisions below are grounded in the current codebase (`src/app.py`, `src/models.py`, `src/ai_parser.py`, `src/scheduler.py`, `src/templates/index.html`, `src/static/js/app.js`). They are deliberately at the architectural / interface level — concrete file paths and snippets belong in issues, not here.

### A. Information architecture: single-page app → multi-destination workspace

- Today `src/templates/index.html` carries two view-tabs (`calendarTab`, `overviewTab`) toggled by `switchView()`. The IA decision is to **promote the "Tasks" overview to the default home** and introduce a top-level nav across four destinations: **Tasks · Calendar · Notes · Mail**.
- Reuse the existing in-page tab-switching pattern for the Tasks↔Calendar toggle (zero migration cost), and extend the same shell (header + content region) to host Notes and Mail as sibling destinations. Whether each destination is a server-rendered route (`/notes`, `/mail`) or a tab inside `/` is an issue-level decision; the **default recommendation is server-rendered routes per destination** for clean separation and so that Notes/Mail can be deep-linked.
- The `login_required` decorator is reused unchanged on all new routes — no auth model change.

### B. Task status workflow: new `status` field

- Add a `status` column to `Task` with an application-level enum of `todo | doing | blocked | done` (stored as a string column for SQLite simplicity; no native ENUM in SQLite).
- **Backward-compat mapping**: `completed=True` ⇔ `status='done'`. On read, `completed` is derived from `status=='done'` (kept for backward compat with `to_dict` and the calendar UI). On write from the kanban, setting `status='done'` also flips `completed=True`; any other status flips `completed=False`.
- The "frozen" flag is orthogonal and unchanged: a task can be `frozen=True` AND `status='doing'` (the calendar won't move it, but the kanban shows it as in-progress).
- A data migration backfills `status` for existing rows: `completed=True` → `'done'`; otherwise → `'todo'`. This migration is the first concrete step of the first kanban issue (and aligns with `doc/TODO.md`'s existing "global user config + `migrate.py` that works against the prod SQLite db" item — reused, not reinvented).
- `Space` ordering within the kanban: defer to the existing priority-then-deadline-then-created ordering produced by the scheduler; no new ordering column introduced in this PRD.

### C. Kanban view (Tasks destination, primary)

- Frontend reuses **SortableJS** (already pinned at `1.15.0` in `index.html`). Two Sortable groups: one for cross-column moves (changes `status`), one for intra-column reorder (updates an ordinal — but see decision B re: ordering; intra-column reorder can be satisfied by reusing the existing priority field as a coarse ordinal, or by debouncing into a new lightweight `kanban_order` integer — issue-level call).
- A **space filter row** at the top: pills populated from `GET /api/spaces`; selecting one filters the kanban to that space's tasks; an "All" pill clears the filter. Filter state is client-side (and persisted to `localStorage` per story 20).
- **Inline create per column**: a "+" affordance at the top of each column opens a minimal inline "new task in this status" form (title + optional priority + optional deadline). Submits via the existing `POST /api/tasks` extended to accept a `status` field (defaults to `todo` to preserve callers like the AI parse flow).
- Cards show: title, priority badge, deadline (if set), space badge. Clicking a card opens the existing `#addTaskModal` (already in `index.html`) repurposed as a full editor.
- Drag into `done` flips `completed=True`; drag out of `done` flips it back — single source of truth is `status`.

### D. Grouped-by-space view (kept as the secondary Tasks view)

- The current `#overviewView` markup and its JS rendering become the secondary view under Tasks, toggled by the existing `switchView('overview')`. **No behavior change** is intended for this view in this PRD — it is preserved, not reworked.

### E. Calendar destination: frozen, demoted

- The calendar (`#calendarView`, FullCalendar wiring in `app.js`, `GET /api/tasks`, `POST /api/schedule`, `GET /api/external-events`, `POST /api/tasks/freeze-day`, `POST /api/tasks/reorder`, `POST /api/tasks/<id>/toggle-freeze`) is kept byte-for-byte. The only change is that the default destination on landing is **Tasks (kanban)**, not Calendar.

### F. Notes module

- New `Note` model: `id`, `space_id` (FK → spaces.id, nullable to allow unfiled notes — explicit decision to permit ""), `title` (String), `content_markdown` (Text), `created_at`, `updated_at`. Serialized via `to_dict()`.
- New routes (all `login_required`): `GET /api/notes?space_id=…`, `POST /api/notes`, `GET /api/notes/<id>`, `PUT /api/notes/<id>`, `DELETE /api/notes/<id>`, `POST /api/notes/<id>/cleanify`.
- **Editor**: a plain `<textarea>` bound to a debounced autosave (e.g. 800ms). No markdown rendering in this PRD — explicitly out of scope. Title is a separate editable field at the top.
- **Cleanify** (`POST /api/notes/<id>/cleanify`): server loads a dedicated system prompt (see decision H), calls the generalized AI provider with the note's current content as the user message, returns the cleaned markdown. Client offers "Apply" (replaces `content_markdown`) with an "Undo" affordance (keep the previous content in memory until the next nav).
- Space-switching on the Notes page reuses the same Space list as Tasks; selecting a different Space swaps the displayed notes list.

### G. Mail module

- New `Mailbox` model: `id`, `label` (String, e.g. "Work inbox"), `host`, `port` (Int), `username`, `password_encrypted` (Text — see security decision below), `use_ssl` (Bool), `use_tls` (Bool), `space_id` (FK → spaces.id, nullable), `created_at`, `updated_at`. No inbox contents are persisted — emails are **fetched live via IMAP** on each open of the mailbox (mirrors the existing `fetch_external_events` live-ICS pattern for calendars).
- New `EmailMessage` is a **transient DTO** (not a persisted model): `{message_id, subject, from, date, snippet, body, unread}` returned by the fetch endpoint. This keeps mail storage cheap and avoids re-implementing an IMAP sync daemon.
- New routes (all `login_required`): `GET/POST /api/mailboxes`, `PUT/DELETE /api/mailboxes/<id>`, `GET /api/mailboxes/<id>/messages` (live IMAP fetch, paginated), `POST /api/mailboxes/<id>/messages/<message_id>/add-task`.
- **`add-task` flow**: server fetches the full email body via IMAP on demand, calls the generalized AI provider with the email-to-task system prompt + the body as the user message, returns a task draft (title, description, priority, deadline, estimated_duration) **pre-tagged with the mailbox's `space_id`**. The client opens the existing `#addTaskModal` with the draft pre-filled for the user to confirm — no silent task creation.
- **Credential security**: mailbox `password_encrypted` is encrypted at rest using a symmetric key derived from the app's `SECRET_KEY` (Fernet or `cryptography.hazmat`). The plaintext password is held in memory only for the duration of an IMAP call. Passwords are never returned by any `GET /api/mailboxes` — only a `has_password` boolean.
- **IMAP library**: Python stdlib `imaplib` + `email` parsing (no new dependency). This matches the project's "stdlib + one HTTP lib" lean style (mirrors `calendar_integration.py` using `icalendar` only).
- **Right-click affordance**: a context menu on each email row in the inbox list; "Add task" is the primary action. (Implementation detail: a small vanilla-JS context menu or a Bootstrap dropdown — issue-level call.)

### H. AI provider generalization: `parse_task` → `complete`

- Today `AIProvider.parse_task(text, system_prompt)` is the only LLM entry point, and `_process_response` is hardcoded to extract a JSON list of task dicts. Generalize: introduce a `complete(system_prompt, user_message) -> str` method on `AIProvider` that returns the raw model text. `parse_task` becomes a thin wrapper: `complete(...)` → `_process_response`.
- `OpenAIProvider` and `AnthropicProvider` each implement `complete` once. `parse_task`, `cleanify_note`, and `email_to_task` are then **module-level functions** in `ai_parser.py` that call `get_ai_provider().complete(...)` with their respective system prompts and post-process the response (JSON extraction for tasks, raw markdown for cleanify, JSON extraction for email-to-task).
- This avoids three parallel provider impls and keeps the existing `get_ai_provider()` URL heuristic as the single selection point.
- All three entry points share the same graceful-degradation pattern: on any exception or empty response, fall back to a trivial derived value (for cleanify: return the original note unchanged; for email-to-task: return a single task with `title = email subject`, `description = first 500 chars of body`, `priority = 5`).

### I. Prompt files: one per LLM use case

- Today `src/config.py` loads `src/prompt.md` as `SYSTEM_PROMPT`. Extend `Config` to also load (lazily, on first access) sibling prompt files: e.g. `src/prompts/notes_cleanify.md`, `src/prompts/email_to_task.md`. `prompt.md` stays where it is (task parsing) to avoid breaking existing behavior.
- Each prompt file is plain markdown loaded into a string at startup; no runtime file reads per request (cache on `Config`).

### J. Audit (ChangeLog) extension

- Existing `ChangeLog` model records `entity_type`, `entity_id`, `old_value`, `new_value` (JSON), `action`, `timestamp`. Extend the set of `entity_type` values to include `note` and `mailbox` (and `email_to_task` as a task-create action with the source mailbox/message_id recorded in `new_value` metadata). No schema change to `ChangeLog` itself — only new writers.

### K. Schema changes summary

| Model | Change |
| --- | --- |
| `Task` | add `status` column (`String`, default `'todo'`); backfill from `completed`. |
| `Note` | new model. |
| `Mailbox` | new model (with `password_encrypted`). |
| `ChangeLog` | no schema change; new `entity_type` values added by writers. |
| `Space`, `CalendarSource`, `db` | unchanged. |

### L. Out-of-scope but flagged for future

- Note markdown rendering (this PRD is source-only per user request).
- Email reply / send (this PRD is read-only inbox + task extraction).
- IMAP background sync / push (live-fetch only, mirroring calendar ICS live-fetch).
- Per-task `kanban_order` ordinal (deferred; reuse priority as coarse ordinal).
- Multi-user / per-mailbox auth (single shared `APP_PASSWORD` model retained).

---

## Testing Decisions

**Highest viable seam: HTTP route-layer integration tests via Flask's test client.** Each feature is exercised end-to-end through its JSON API (`POST /api/tasks`, `POST /api/notes/<id>/cleanify`, `POST /api/mailboxes/<id>/messages/<id>/add-task`, etc.) and asserted on response shape + persisted DB state. This matches the project's existing shape (everything is route handlers + SQLAlchemy), tests external behavior (not implementation), and avoids brittle unit tests against private helpers.

**Test harness bootstrapping (gap to close):** the repository currently has **no test directory and no test runner configured** (verified: `src/` contains only the source modules; no `tests/`, no `conftest.py`, no `pytest` in dependency manifests that I observed). The first issue this PRD decomposes into MUST, as its first concrete step, bootstrap a minimal `pytest` + `pytest-flask` (or plain Flask test client) harness with an in-memory SQLite fixture, a stubbed `AIProvider` that returns canned responses, and a fixture that patches `imaplib` to return canned email fixtures. Subsequent issues reuse this harness without rebuilding it.

**Test seams, per pillar** (all via the Flask test client, asserting on JSON responses + DB rows):

- **Kanban / Task status** — assert: `POST /api/tasks` with `status='doing'` persists that status; `PUT /api/tasks/<id>` moving `status` `todo → done` flips `completed=True`; dragging is not unit-tested (it's a gesture over the same `PUT`); the grouped-by-space view is not regression-tested at the DOM level but via its data source `GET /api/tasks`.
- **Notes** — `POST /api/notes` creates a row; `PUT /api/notes/<id>` updates `content_markdown`; `POST /api/notes/<id>/cleanify` with a stubbed provider returning `"cleaned"` asserts the endpoint returns `{"content": "cleaned"}` and does NOT auto-persist (apply is a separate `PUT`).
- **Mail** — `POST /api/mailboxes` persists `password_encrypted` (and `GET /api/mailboxes` does NOT return the plaintext); `GET /api/mailboxes/<id>/messages` with `imaplib` patched returns the canned list; `POST .../add-task` with `AIProvider.complete` patched returns a task draft pre-tagged with the mailbox's `space_id` and does NOT silently persist (the user confirms via the existing task-create flow).
- **AI generalization** — unit-level (acceptable here because the AIProvider is a pure seam): a fake provider subclass returns `"raw model text"` and `parse_task`/`cleanify_note`/`email_to_task` correctly post-process it. This is the one place a unit test is preferred over an HTTP test, because the LLM is the seam.
- **ChangeLog** — asserted as a side-effect of the route-layer tests above (e.g. after `DELETE /api/notes/<id>`, a `ChangeLog` row with `entity_type='note'`, `action='delete'` exists).

**Prior art in the codebase:** none — there is no existing test suite to mirror. The harness this PRD mandates will become the prior art for all future issues.

**What does NOT get tested:** front-end drag-drop interactions (out of seam reach without a browser driver; not worth introducing Playwright for this PRD), the actual LLM output quality (out of scope — stubbed), and the calendar regression (kept byte-for-byte — its existing manual-verification posture is unchanged; adding coverage for it is out of scope for this PRD and would be a separate effort).

---

## Out of Scope

1. **Note markdown rendering** — explicitly deferred by the user ("for now don't bother to render it"). A future PRD will add live preview / rendered view.
2. **Email send / reply / compose** — read-only inbox + task extraction only.
3. **IMAP background sync or push notifications** — live-fetch only (mirrors the calendar's live-ICS pattern).
4. **Calendar changes of any kind** — the calendar is frozen as-is per the user's explicit instruction.
5. **Grouped-by-space overview rework** — kept as-is; only its container changes (it becomes the secondary Tasks view).
6. **Per-task `kanban_order` ordinal column** — deferred; the kanban reuses priority as a coarse intra-column ordinal. Introducing a dedicated ordinal is a future enhancement if intra-column ordering feels wrong in practice.
7. **Per-user accounts / per-mailbox auth** — the single shared `APP_PASSWORD` model is retained.
8. **Mobile-native / responsive rework** — the existing desktop-first layout is extended; a dedicated responsive pass is a separate PRD.
9. **Migration tooling beyond SQLite** — `migrate.py` continues to target the prod SQLite db (per `doc/TODO.md`'s existing intent).
10. **LLM output quality / evals** — AI behavior is stubbed in tests; qualitative eval is a separate concern.

---

## Further Notes

- **Vision statement (from the user, verbatim intent):** *"streamlined, friction-free, all-in-one-place workflow/workspace that is as ADHD-friendly as possible, where everything is available in as little clicks as possible."* Every issue decomposed from this PrePRD should be evaluated against this bar — if a proposed implementation adds a click or a context switch, push back during the issue's grilling.

- **No grilling performed.** Per the user's explicit instruction ("don't grill me on it as I don't have time yet"), this PrePRD is a one-shot capture, not the output of an alignment interview. Before decomposing into issues, a `grilling` pass is strongly recommended to validate: (a) whether Tasks should be the literal default landing or whether a "Today" dashboard is wanted; (b) the precise column semantics of `blocked` vs `todo` (is `blocked` a status or a flag?); (c) whether mailboxes should be live-IMAP (this PRD) vs persisted (heavier but enables search); (d) the cleanify "apply / undo" UX; (e) credential encryption key management (derive from `SECRET_KEY` is convenient but rotates with the app secret — may want a dedicated key).

- **Context update needed (per planner read-only rule, the `build`/`automode` agent applies these during implementation):**
  - `.opencode/context/CONTEXT.md` — the "Product" line and "Current focus" section need to reflect the shift from "smart calendar" to "unified ADHD-friendly workspace"; add Notes and Mail to the module map.
  - `.opencode/context/topics/data-model.md` — add `Task.status`, `Note`, `Mailbox` models; document the `completed ⇔ status=='done'` mapping.
  - `.opencode/context/topics/ai-parsing.md` — generalize to cover `complete()` plus the three entry points (`parse_task`, `cleanify_note`, `email_to_task`); document the new prompt files.
  - New deep-dive (create when built): `.opencode/context/topics/notes.md` and `.opencode/context/topics/mail.md` — not created by planner (read-only outside `.opencode/plans/**`); flagged for the implementer.
  - `doc/TODO.md` — invalidate or mark-complete the items that this PrePRD supersedes (global user config + `migrate.py` is partially subsumed by decision B's status backfill migration; click/drag-to-create is subsumed by the kanban inline-create; "advanced task creator modal" is partially subsumed by keeping the AI parse flow).

- **Lifecycle note:** because this artifact is named `PrePRD` (per the user's request) rather than `PRD`, the `to-issues`/`NNN_PRD_*` scanners should treat it as a PRD-equivalent for sequence-number purposes (it occupies slot `000`). When the user later wants to grill and align, the cleanest path is to rename this file to `000_PRD_unified-adhd-workspace.md` and flip `Status: Draft → Aligned` in place, preserving the ID.

- **Sequence-number hygiene:** this is the first artifact in `.opencode/plans/`, so it takes `000`. Future `PRD`/`PrePRD` files start at `001`. Issue files (under `issues/`) start their own counter at `000` and are decomposed from this PrePRD only after the user confirms the next step.
