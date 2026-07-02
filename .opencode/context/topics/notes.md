# Notes Module

> In-app ADHD-friendly note capture with promote-to-task and Cleanify. PRD `001` (archived: `.opencode/plans/archive/001_PRD_notes.md`). Notes are a first-class destination alongside the calendar — thoughts get captured into the currently-selected Space, tidied with one click, and promoted into a task with a single selection+click, all without crossing application boundaries.

## Information architecture (unified shell, 2026-07)
- Notes is a **destination inside the unified shell** (`index.html`), not a separate page: `notes.html` was removed and `/notes` now redirects to `/#notes` (session-check-and-redirect; `login_required` returns JSON 401, not an HTML redirect, so pages do their own check). All `/api/notes/*` JSON routes (in `src/routes/notes.py`) ARE `@login_required`.
- Frontend is the `window.NotesView` module in `src/static/js/notes.js` (IIFE, **lazy init on first entry** — `NotesView.enter()` called by the shell's `switchDestination('notes')`; CodeMirror `refresh()` on every entry because CM5 mis-measures when initialized hidden).
- Reuses the existing `GET /api/spaces` for its Space switcher; filter state (selected Space) persisted to `localStorage`.
- Auth: no new auth model — reuses the single shared `APP_PASSWORD` + session cookie.

## Editor: EasyMDE (CodeMirror 5)
- Loaded via CDN (`<script src="https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.js">` + CSS), matching the project's no-build CDN pattern (FullCalendar / SortableJS / Bootstrap). Frontend logic in `src/static/js/notes.js`.
- **Mandatory config:** `autosave: {enabled: false}` (EasyMDE's built-in localStorage autosave would shadow the backend `PUT` path), `status: false`.
- Toolbar = the **standard formatting set** (bold/italic/strikethrough, headings 1-3, quote, lists, code, hr, link, image, preview, side-by-side, guide — `table` and `fullscreen` deliberately removed per user feedback 2026-07: table hogged a whole toolbar line) **plus** the three custom buttons: `add-task` (promote selection to task), `cleanify` (tidy whole note via LLM), `undo-cleanify` (single-step restore). (The original design shipped custom-buttons-only to keep formatting as Cleanify's job; user feedback 2026-07 asked for the toolbar back.) The custom actions are also surfaced as standalone HTML buttons (`#notePromoteBtn`, `#cleanifyBtn`, `#undoCleanifyBtn`) below the editor.
- Selection handling (promote-to-task contract): `editor.codemirror.getSelection()` reads the selection; `editor.codemirror.somethingSelected()` toggles the `add-task` button's disabled state on `cursorActivity`/`change` (robust across browsers, wrapped lines, and iPad soft-keyboards).
- Content replacement (Cleanify Apply): `editor.value(cleanedText)` overwrites the buffer; the CM5 `change` event fires the existing debounced `PUT`-on-input autosave, so the cleaned text persists through the normal path (no special Apply step).

## Deferred persistence (client-side lifecycle)
- "+" opens an empty editor bound to the currently-selected Space with **no row created yet**.
- A debounced (~800ms) autosave fires on every content change. First time it would fire with non-empty `content_markdown` (or non-empty `title`) → `POST /api/notes`; subsequent saves → `PUT /api/notes/<id>`.
- Navigating away / unmounting while `content_markdown == ""` AND `title == ""` AND no prior POST = nothing persisted. No empty "Untitled" cadavers.

## Routes (`src/routes/notes.py`, all `login_required`, JSON in/out)
- `GET /api/notes?space_id=<id>` → note DTOs for that Space, ordered by `updated_at` desc (full DTOs incl. content; client previews content for the list).
- `POST /api/notes` → `{space_id, title?, content_markdown?}` creates + logs `entity_type='note', action='create'`. `space_id` NOT NULL enforced.
- `GET /api/notes/<id>` → single DTO (404 if missing).
- `PUT /api/notes/<id>` → any subset of `{title, content_markdown, space_id}` → updated DTO + `action='update'`. Used for ordinary debounced autosave AND Cleanify Apply.
- `DELETE /api/notes/<id>` → 204 + `action='delete'`.
- `POST /api/notes/<id>/cleanify` → body `{}` → `{content: <string>}`. Builds `Config.NOTES_CLEANIFY_PROMPT` + the note's Space context suffix, calls `cleanify_note_with_ai(note.content_markdown, system_prompt)`. **Does not persist** (the client replaces editor content + the existing debounced `PUT` autosave persists). On AI failure → `{content: <original note content>}` (graceful degradation via `cleanify_note_with_ai`'s try/except).
- `POST /api/notes/<id>/promote-to-task` → `{selected_text}` → list of task draft DTOs (same shape `/api/tasks/parse` returns). Builds system prompt = `Config.SYSTEM_PROMPT` + available-spaces suffix (same as `/api/tasks/parse`), calls `parse_task_with_ai(selected_text, ...)`, defaults each draft's `space_id` to `note.space_id` when the LLM returns `None`. **Does not persist a Task**; client opens the task-confirm modal, user confirms → existing `POST /api/tasks` creates the task. Note left completely untouched.

## Frontend task-confirm modal
- The draft-confirm modal is the **shared `window.TaskDraftModal`** (`src/static/js/task_draft_modal.js`), used by BOTH promote-to-task and the Mail module's email-to-task. `confirmDrafts(drafts, spaces)` opens the modal once per draft in sequence (cancel stops the loop) and POSTs each confirmation to the existing `POST /api/tasks`; it resolves with the count created, after which the caller refreshes the board via the global `loadTasks()`.

## Cleanify Undo (single-step, client-side)
- On Cleanify: `previousContent` (= `state.lastCleaned`) stores the pre-clean buffer, `editor.value(resp.content)` replaces in place, "Undo Cleanify" shown.
- On Undo: `editor.value(previousContent)` restores, "Undo" hidden. `lastCleaned` reset to `null` on note switch / editor clear. NOT an ephemeral toast — persistent until clicked or until next Cleanify overwrites (per PRD decision E: an accidental click must be reversible reliably even after a stray keystroke).

## Testing
- HTTP route-layer integration tests via the Flask test client + one unit-level seam on the AI provider's `cleanify` method (see `.opencode/context/topics/ai-parsing.md`). Harness in `tests/conftest.py`: in-memory SQLite (`StaticPool`), per-test schema reset + default-space seeding (work/study/association), `StubAIProvider` (canned `parse_task` + `cleanify`), `stub_ai_provider_raising`, `sample_note`, `login(client)` helper. Test files: `test_parse_task_regression.py` (000), `test_notes_crud.py` (001), `test_cleanify_ai_seam.py` (002), `test_cleanify_prompt_loaded.py` (003), `test_cleanify_route.py` (004), `test_promote_to_task_route.py` (005).
- Frontend interactions (drag/select/EasyMDE) are NOT covered by automated tests (no browser driver) — manual verification only.

## Invariants (do NOT break)
- No `source_note_id` column on `Task` (PRD Out-of-Scope 4 — conceptual link only).
- `parse_task` code path unchanged in signature/behaviour (regression test 000 anchors this).
- No `AIProvider.complete()` generalization (decision F — `cleanify` is a sibling method).
- Notes Cleanify prompt loaded once at startup and cached; no per-request file reads.
