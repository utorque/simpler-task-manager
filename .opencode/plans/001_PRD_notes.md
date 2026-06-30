# PRD: Notes (ADHD-friendly in-app note capture with promote-to-task and Cleanify)

- **ID**: 001
- **Status**: Aligned
- **File**: `001_PRD_notes.md`
- **Parent vision**: `000_PrePRD_unified-adhd-workspace.md`

## Problem Statement

In the user's actual workflow, the calendar is not the front door — notes are. Thoughts, meeting fragments, and stream-of-consciousness captures get dumped into OneNote because that is the lowest-friction surface, then sit there as messy text until the user manually copies a fragment back into the calendar app, opens the AI task creator, pastes, and confirms. That copy-paste-into-the-other-tool loop is exactly the multi-tool, multi-click friction the product exists to kill, and it scatters context for a Space (work / study / association) across TwoNote + the calendar instead of keeping it in one place.

Two specific pains:
1. Captured text in OneNote is *detached* from the Space model — the user has no way to say "this is a study note, treat it that way" — and the path from note → task requires crossing application boundaries.
2. Messy ADHD-style captures never get tidied because there is no one-tap "clean this up" affordance closely bound to where the text lives. The cleaning-and-the-capturing happen in different tools, so neither gets done.

## Solution

Add a **Notes** destination to the app, organized by Space, that: (a) lets the user capture a thought in a single click into the currently-selected Space's notes; (b) lets the user select lines inside a note and click one button to promote them into a task using the existing pasted-text → AI-parse flow, with the task's Space pre-filled from the note's Space; (c) provides a one-tap **Cleanify** action that runs the note through the LLM with a minimalistic tidy-up prompt and replaces the editor content in place, with a single-step persistent Undo; (d) logs note create/update/delete to the existing ChangeLog.

The editor itself is intentionally minimal — a plain markdown `<textarea>` (no live rendering), a separate title field, debounced autosave, and the two action buttons. Reusing the existing `parse_task_with_ai` flow for promote-to-task (no new AI code path for tasks) and using a *new* `cleanify` method on the existing `AIProvider` base class for Cleanify (no refactor of `parse_task` itself) keeps blast radius small and makes the LLM seam the one place new AI behavior enters.

## User Stories

### Notes module — capture & lifecycle

1. As the user, I want a Notes destination reachable from a top-level nav, so that I can jump to my notes from anywhere.
2. As the user, I want the Notes page to show the list of notes for the currently-selected Space, so that notes stay organized by Space exactly like tasks do.
3. As the user, I want a Space switcher on the Notes page identical to Tasks', so that I can move between Spaces without leaving Notes.
4. As the user, I want every note to belong to exactly one Space, so that notes inherit their Space context (and so a note's promote-to-task always produces a properly-spaced task, never an unfiled one).
5. As the user, I want clicking "+" to open an empty editor bound to the currently-selected Space immediately, so that capture is one click.
6. As the user, I want the new row to be persisted only on the first non-empty (debounced) autosave, so that an accidental click + navigate-away leaves no empty "Untitled" cadaver behind.
7. As the user, I want the editor to autosave my content with a debounce as I type, so that I never lose a thought to a missed save.
8. As the user, I want a separate editable title field at the top of the editor, so that the title is independent of the body.
9. As the user, I want an empty title to display as "Untitled" in the list, with a preview of the first non-empty content line, so that I can find a note I never bothered to title.
10. As the user, I want the notes list to be flat and ordered by last-updated-descending, so that I naturally see the note I was just editing at the top without manual ordering.
11. As the user, I want each list row to show title (or "Untitled"), last-edited relative timestamp, and a short content preview, so that I can recognize the note at a glance.
12. As the user, I want to delete a note with a confirm affordance, so that stale notes can be removed deliberately, not accidentally.
13. As the user, I want the note editor to be a markdown source editor, so that I write markdown directly. Live preview is a nice-to-have if it's a config-only flip with no extra deps (per decision L); not a blocker.

### Promote-to-task

14. As the user, I want to select a range of lines inside a note and click "Add as task", so that turning a captured thought into a task is a single gesture.
15. As the user, I want the selected text to be sent through the existing pasted-text → AI parse flow, so that my messy captured text becomes a structured task with title / priority / deadline / estimated_duration derived exactly as if I had pasted it into the AI task creator.
16. As the user, I want the resulting task draft to open in the existing task editor modal pre-filled, with the Space set to the note's Space and the title / priority / deadline / duration pre-derived by the AI, so I only need to confirm.
17. As the user, I want the note to be left completely untouched after promotion (no markers, no strike-through, no removed text), so that promoting again later doesn't silently duplicate, and so the note stays as my raw capture.
18. As the user, I want a clear failure toast if AI is unreachable during promotion, so I know whether the task was created.

### Cleanify

19. As the user, I want a "Cleanify" button on each note, so that I can turn my messy stream-of-consciousness text into a cleaner version with one click.
20. As the user, I want Cleanify to replace the editor content in place immediately on click, so that capturing the value is a single gesture (not preview-then-apply).
21. As the user, I want a persistent single-step "Undo Cleanify" button held visible until I explicitly dismiss it or run Cleanify again, so that an accidental click can be reversed reliably even if I type a keystroke right after.
22. As the user, I want the Cleanify result to flow through the normal debounced autosave path on Apply (i.e. it's an ordinary `PUT`), so that the cleaned version persists the same way any edit does.
23. As the user, I want the Cleanify system prompt to be aware of the note's Space description, so that the LLM's tidying matches the context the note lives in (a "study" note and a "work" note get cleaned differently).
24. As the user, I want Cleanify to degrade gracefully when the AI is unreachable or returns nothing usable, so that the call returns my note's original content unchanged instead of erroring.

### Audit

25. As the user, I want note create/update/delete to be recorded in `ChangeLog` (entity_type='note', actions create/update/delete), so that the existing audit pattern extends to the new entity type.
26. As the user, I want a Cleanify Apply to be recorded as a normal note update, so that the audit trail reflects that the content changed (no special "cleanify" action).

### AI plumbing (Notes-scoped only)

27. As the user, I want the same AI provider configuration (`AI_API_KEY` / `AI_API_BASE_URL` / `AI_MODEL`) to power both task parsing and note cleaning, so that I configure the LLM once for the whole app.
28. As the user, I want Cleanify to use a dedicated tidy-up system prompt (separate from the task-parsing prompt), so that the LLM's behavior matches the job (clean markdown, do not invent tasks).
29. As the user, I want Cleanify's punctuation / line-break / structural improvements to preserve the semantic meaning of my notes verbatim where the intent is clear, so that tidying never silently changes what I meant.

## Implementation Decisions

### A. The Notes module is additive only

- The existing calendar, scheduler, AI task-parsing flow (`parse_task_with_ai`), and `Task` model are **not** modified by this PRD. Notes adds new code; it does not refactor existing code paths.
- One exception: the `AIProvider` base class and its two concrete providers gain a new method (decision F). The existing `parse_task` path is untouched and still covered by its own regression guard test (decision H).

### B. Information architecture

- The Notes destination lives at a server-rendered route `/notes` (separate from `/`), reachable from a new top-level nav link. Deep-linkable and bookmark-friendly. The current `/` (calendar) is unchanged.
- The new Notes page reuses the existing Space list (`GET /api/spaces`) for its Space switcher; selecting a Space filters the displayed notes list. Filter state is client-side, persisted to `localStorage` (same convention as the planned kanban).
- Auth: `/notes` and all `/api/notes/*` routes reuse the existing `login_required` decorator. No new auth model.

### C. Note model

- New `Note` model, table `notes`: `id` (PK), `space_id` (Integer, FK→spaces.id, **nullable=False** — every note has a Space), `title` (String, nullable — empty title is valid and shows as "Untitled" in the list), `content_markdown` (Text, default empty), `created_at`, `updated_at` (DateTime). Serialized via `to_dict()` returning `{id, space_id, title, content_markdown, created_at, updated_at}`.
- `space_id` is NOT NULL: the Notes page is always opened in the context of a selected Space, and the "+" create button inherits that Space. There is no "unfiled" pseudo-space.
- Title is a separate column (not derived from content). Empty title is a valid stored state; the list view falls back to the literal string "Untitled" plus a preview of the first ~80 chars of content for the row label.
- The table auto-creates on app startup via the existing `db.create_all()` call (`app.py` invokes it once at boot). No `migrate.py` change is required — no columns are added to existing tables.

### D. Routes (all `login_required`, all JSON in/out)

- `GET /api/notes?space_id=<id>` → list of notes for the Space, ordered by `updated_at` desc. Returns the full DTO list (titles + content_markdown). The client previews content client-side for the list view.
- `POST /api/notes` → body `{space_id, title?, content_markdown?}`. Creates a row. Returns the new note DTO.
- `GET /api/notes/<id>` → single note DTO.
- `PUT /api/notes/<id>` → body with any subset of `{title, content_markdown, space_id}`. Updates the row, returns the new DTO. Used both for ordinary debounced autosave and for Cleanify Apply.
- `DELETE /api/notes/<id>` → 204 on success.
- `POST /api/notes/<id>/cleanify` → body `{}` (no payload). Returns `{content: "..."}`. **Does not persist**; the client replaces the editor content in place and the existing debounced autosave path persists it via a normal `PUT`. On AI failure or empty response, returns `{content: <the note's current content>}` so the client simply no-ops.
- `POST /api/notes/<id>/promote-to-task` → body `{selected_text: "..."}`. Returns the parsed task draft DTO (same shape as `POST /api/tasks/parse` already returns). **Does not persist a task**; the client opens `#addTaskModal` pre-filled (including `space_id = note.space_id`) for the user to confirm via the existing `POST /api/tasks`. The note is left completely untouched.
- All mutations log to `ChangeLog`: `entity_type='note'`, `action in {create, update, delete}`. `old_value`/`new_value` are JSON-serialized `Note.to_dict()` snapshots. Cleanify Apply is just an update. Promote-to-task logs as `entity_type='task', action='create'` via the existing task-creation code path (no breadcrumb back to the note per decision G).

### E. Create lifecycle (deferred persistence)

- The "+" click opens an empty editor bound to the currently-selected Space **client-side only** — no row exists yet.
- A debounced autosave (~800ms) fires on every content change. The first time it would fire with non-empty `content_markdown` (or non-empty `title`), the client issues `POST /api/notes`; subsequent debounced saves issue `PUT /api/notes/<id>`.
- Navigating away or unmounting the editor while `content_markdown == ""` AND `title == ""` AND no POST has been issued = nothing is persisted. No empty "Untitled" cadavers.
- If the user makes one keystroke and the browser crashes before the first debounce fires, that one keystroke is lost (acceptable).

### F. AI provider addition — `cleanify` on `AIProvider` (NOT a `complete()` refactor)

- The base class `AIProvider` gains a new method: `cleanify(self, note_text: str, system_prompt: str) -> str`. Both `OpenAIProvider` and `AnthropicProvider` implement it.
- `cleanify` mirrors `parse_task`'s HTTP setup (headers, endpoint, model selection) **but returns raw model text** rather than extracting a JSON list of task dicts. The HTTP boilerplate is similar to `parse_task`'s; some structural duplication is accepted and preferred over a base-class `complete()` refactor (which the user explicitly rejected for blast-radius reasons).
- `parse_task` on `AIProvider`, `OpenAIProvider`, `AnthropicProvider`, and the top-level `parse_task_with_ai(text, system_prompt)` factory are **unchanged** in signature and behaviour.
- A new top-level factory `cleanify_note_with_ai(note_text, system_prompt) -> str` calls `get_ai_provider().cleanify(note_text, system_prompt)` and is the single entry point the route handler uses.
- Graceful degradation: on any exception or empty response, `cleanify_note_with_ai` returns the input `note_text` unchanged. The route handler therefore always has a usable response.

### G. Promote-to-task: reuse, do not duplicate

- Promote-to-task calls `parse_task_with_ai(selected_text, system_prompt)` exactly as the existing `/api/tasks/parse` route does. No new AI code path.
- The route handler builds the system prompt the same way `/api/tasks/parse` does: `Config.SYSTEM_PROMPT` + the available spaces list. (This is to keep the LLM's space-list awareness consistent — the user is creating a task, so the LLM must see the spaces.)
- The created task's `space_id` defaults to the note's `space_id` when the LLM doesn't pick one, but the LLM is free to choose a different space if the note's content fits another Space better. The user confirms in `#addTaskModal`.
- No `source_note_id` column on `Task`. The note is not modified. No back-reference. (Per grilling: a future "jump from task to note" affordance can be added later as a nullable FK if it turns out to matter; landing it without proven need is speculative scope.)

### H. Prompt loading & the cleanify prompt contract

- `Config` loads a new file `src/prompts/notes_cleanify.md` once at startup into `Config.NOTES_CLEANIFY_PROMPT` (cached, sibling to `SYSTEM_PROMPT`). Hot reload requires app restart (acceptable).
- The route handler for `POST /api/notes/<id>/cleanify`:
  1. Loads the note (404 if missing).
  2. Reads `Config.NOTES_CLEANIFY_PROMPT`.
  3. Appends the **note's Space description** to the system prompt (mirroring how `/api/tasks/parse` appends available spaces). Format: `"\n\nNote's Space context:\nName: <space.name>\nDescription: <space.description or "">"`
  4. Calls `cleanify_note_with_ai(note.content_markdown, system_prompt)`.
  5. Returns `{content: <returned text>}`.
- **Prompt authoring contract (carried into the prompt-authoring issue):** the `notes_cleanify.md` prompt MUST be minimalistic. It makes the note more readable but NEVER changes anything that MAY alter the meaning. Better to leave something unchanged than to assert something not clear. Specifically, the prompt must, at minimum, direct the LLM to: tidy punctuation, normalize line breaks and paragraph breaks, normalize list formatting, and otherwise preserve the user's wording and intent verbatim. It must NOT invent facts, summarize away specifics, change bullet points into prose that loses information, or rename entities.

### I. Test harness (owned by the first issue of this PRD)

- The repository currently has no tests, no `tests/` dir, and no pytest configured. The first issue bootstraps a minimal `pytest` + `pytest-flask` + in-memory SQLite test harness: `tests/conftest.py` with a Flask app fixture, an in-memory `db.create_all()` fixture, and a `StubAIProvider` returning canned text for both `parse_task` and `cleanify`.
- The seam chosen is **HTTP route-layer integration tests via the Flask test client**. Each feature is exercised end-to-end through its JSON API and asserted on response shape + persisted DB state.
- One additional unit-test seam is accepted: the `cleanify` method on `AIProvider` is a pure seam (input note text + input system prompt → output text), so a `StubAIProvider` subclass returning `"cleaned"` is used to unit-test `cleanify_note_with_ai`'s post-processing (graceful degradation, identity-on-error) without going through the route layer.
- This is the most pragmatic seam: matches the project's route-handler shape, tests external behaviour (not implementation), and avoids brittle unit tests against private helpers.

### J. Audit extension

- Existing `ChangeLog` model: no schema change. New writers pass `entity_type='note'` and `action in {create, update, delete}` with JSON-serialized `to_dict()` snapshots in `old_value`/`new_value`.
- Promote-to-task flows through the existing task-creation code path (the `POST /api/tasks` handler that the modal submits to) and therefore logs as `entity_type='task', action='create'` with no special metadata.

### K. Schema changes summary

| Model | Change |
| --- | --- |
| `Note` | **new model** (table `notes`). |
| `Task` | unchanged. |
| `Space`, `CalendarSource`, `ChangeLog`, `db` | unchanged. |

### L. Editor component: EasyMDE (CodeMirror 5 under the hood)

- The note editor is **EasyMDE** (the maintained SimpleMDE fork), loaded from CDN as `<script src="https://cdn.jsdelivr.net/npm/easymde/dist/easymde.min.js">` + matching CSS, matching the project's existing no-build CDN-loading pattern for FullCalendar/SortableJS/Bootstrap.
- Selected by grilling over plain `<textarea>`, EasyMDE, raw CodeMirror 5, CodeMirror 6, Ace, and rich-text WYSIWYG libs (Milkdown/Tiptap/Lexical/ProseMirror). CodeMirror 6 was discarded (requires a bundler; doesn't fit the no-build CDN pattern). Ace was discarded (IDE-flavor, ~280KB, less markdown-oriented). Rich-text WYSIWYG libs were discarded (require build step + contradict the markdown-source-editor decision). Plain `<textarea>` was a strong contender but loses on (i) robust cross-browser selection API (which the promote-to-task interaction depends on, especially across wrapped lines and iPad soft-keyboards), (ii) markdown-aware line-wrap / list continuation, and (iii) a free safety net (CM5's native Ctrl+Z history) on top of our deliberate single-step Cleanify Undo. Raw CM5 was a strong contender but loses to EasyMDE on glue-code cost (EasyMDE ships the toolbar abstraction we need; raw CM5 means ~50 LoC of custom toolbar HTML+JS).
- **Toolbar is explicit and minimal** — three custom buttons only, NO formatting toolbar:

  ```
  toolbar: [
      "|",
      {name: "add-task", action: <promote-to-task handler>, className: "fa fa-plus-square", title: "Add as task"},
      {name: "cleanify", action: <cleanify handler>, className: "fa fa-broom", title: "Cleanify"},
      {name: "undo-cleanify", action: <undo handler>, className: "fa fa-undo", title: "Undo Cleanify"},
  ]
  ```

  Rationale: the user's "minimalistic" preference + the Cleanify prompt contract ("LLM tidies formatting, NOT the user"). A bold/italic/heading toolbar *collides* with Cleanify's job and would invite the user to format by hand, which the system is supposed to do for them.
- **Selection handling (promote-to-task contract)**: `editor.codemirror.getSelection()` returns the selected text as a string. `editor.codemirror.on('cursorActivity', cb)` toggles the "Add as task" button's `disabled` attribute based on `editor.codemirror.somethingSelected()`. When "Add as task" is clicked with an empty selection, it is in a disabled state (no silent no-op, no error). CM5's `somethingSelected()` / `getSelection()` are robust across browsers, wrapped lines, and soft-keyboard selection edge cases.
- **Content replacement (Cleanify Apply)**: `editor.value(cleanedText)` overwrites the editor content; the client holds the previous content in a JS variable for the single-step Undo; after the debounced autosave fires (CM5 `input` event), the `PUT` persists the cleaned text through the normal path.
- **Mandatory EasyMDE config caveats the implementer MUST respect**:
  - `autosave: { enabled: false }` — EasyMDE's built-in autosave writes to `localStorage`, which would shadow the backend `PUT` path and cause confusion. The app uses its own debounced `PUT`-on-input autosave.
  - `toolbar:` MUST be the explicit custom array above, NOT the default formatting toolbar.
  - `spellChecker: true` is acceptable (left on).
  - `status: false` (no built-in word/line/cursor status bar; the Notes page renders its own minimal autosave indicator if needed).
- **Live preview / rendering — nice-to-have, not blocked.** Per user direction ("don't block the render: if it's practical and easy to use with our application, it's a nice to have"). EasyMDE ships with a built-in side-by-side preview (`toolbar: ["preview"]`, `previewImagesInEditor`, `renderingConfig`). If enabling it is a config-only flip with no new dependency, glue code, or layout overhaul, the implementer MAY enable side-by-side preview in the Notes editor as a bonus. If it turns out to require non-trivial integration (custom renderers, sanitizer config, markdown-it plugins), defer to a follow-up PRD per Out-of-Scope item 2. The implementer makes the call based on what they find in EasyMDE's options during implementation; no.preview feature is a blocker for shipping v1.

## Testing Decisions

**Highest viable seam: HTTP route-layer integration tests via Flask's test client, plus one unit-test seam on the AI provider's `cleanify` method.**

- **Prior art in the codebase:** none. There is no test directory; the harness bootstrapped by the first issue becomes the prior art for all future issues, this PRD included.
- **Test harness bootstrap (the gap):** `pytest` + `pytest-flask`, `tests/conftest.py` with: (a) a Flask app fixture using in-memory SQLite (`sqlite:///:memory:`), `db.create_all()` once; (b) a `StubAIProvider` registering both `parse_task` (returns a canned task list) and `cleanify` (returns canned markdown), patched into the module under test; (c) a client fixture wrapping the app's test client. This harness is owned by the first issue of this PRD's decomposition.
- **A good test in this PRD** asserts on JSON response shape + DB row state via the model API (not raw SQL). It uses the public HTTP API. It does not assert on private helpers.
- **Per-pillar tests** (all via Flask test client unless noted):
  - **Notes CRUD** — `GET /api/notes?space_id=X` returns notes for X ordered by `updated_at` desc; `POST /api/notes` with `{space_id, content_markdown}` creates a row and a `ChangeLog` entry `entity_type='note', action='create'`; `PUT` updates; `DELETE` removes and logs.
  - **Deferred persistence** — not directly testable at the HTTP layer (it's client-side behaviour); covered by the unit-level test that `POST /api/notes` accepts empty `content_markdown` if and only if `title` is non-empty (so the client-side "first non-empty autosave" works).
  - **Promote-to-task** — `POST /api/notes/<id>/promote-to-task` with `{selected_text: "..."}` and the stub provider returns a task draft DTO matching the shape `POST /api/tasks/parse` returns, with `space_id` defaulting to the note's `space_id` when the stub doesn't pick one; the note is unchanged after the call (assert on `content_markdown`); **no `Task` row is created** by the promote call itself (the client must still POST to `/api/tasks`).
  - **Cleanify route** — `POST /api/notes/<id>/cleanify` with the stub provider returning `"cleaned"` asserts the endpoint returns `{content: "cleaned"}` and **does not** persist (assert the note's `content_markdown` is unchanged in DB after the call). When the stub provider raises, the endpoint returns `{content: <original note content>}` (graceful degradation).
  - **Cleanify AI seam** (unit-level — the one allowed unit test, because the LLM is the seam): a `StubAIProvider.cleanify` returns `"cleaned"` regardless of input → `cleanify_note_with_ai("messy", "system-prompt")` returns `"cleaned"`; a `StubAIProvider.cleanify` that raises → `cleanify_note_with_ai` returns the input text unchanged.
  - **Prompt loading** — `Config.NOTES_CLEANIFY_PROMPT` is non-empty at startup; the prompt file's existence is a precondition (the test harness fixture includes a stub `notes_cleanify.md`).
  - **Space description injection** — the route handler for `cleanify` includes the note's Space's `description` in the system prompt: assert via a spy on `cleanify_note_with_ai` capturing the `system_prompt` argument and checking it contains the Space's description.
  - **ChangeLog** — asserted as a side-effect of the route-layer tests above (e.g. after `DELETE /api/notes/<id>`, a `ChangeLog` row with `entity_type='note', action='delete'` exists).

**What does NOT get tested:**
- Front-end drag/select interactions (no browser driver; not worth introducing Playwright for this PRD).
- Actual LLM output quality (the stub returns canned text; qualitative prompt evaluation is a separate concern and is not asserted in tests).
- The exact wording of `notes_cleanify.md` (the file is a fixture, not a contract — but the issue that authors it has its own contract checklist, see decision H).
- Calendar regression (unchanged surface; manual verification only).

## Out of Scope

1. **Tasks-sidebar-on-Notes-page** — the "see tasks alongside notes" insight is real but depends on the Tasks-kanban `status` field, which is a separate future PRD. Deferred to a follow-up PRD once the kanban exists.
2. **Markdown rendering / live preview as a hard requirement** — preview is a nice-to-have per decision L (enable if config-only, defer otherwise), not a v1 ship blocker. A dedicated "rich rendering / WYSIWYG" PRD is a separate follow-up if EasyMDE's preview turns out insufficient.
3. **Multi-step note version history** — Cleanify Undo is single-step, client-side, in-memory only. A `NoteVersion` table is out of scope.
4. **Note↔task back-references** — `source_note_id` is not added to `Task` in this PRD. The link between a promoted task and its note is conceptual only.
5. **Tasks-kanban / Mail / unified IA** — those belong to other PRDs under the parent PrePRD `000_PrePRD_unified-adhd-workspace.md`.
6. **AIProvider `complete()` refactor** — explicitly rejected for blast-radius reasons; `cleanify` is added as a sibling method to `parse_task`, not as a generalization.
7. **Auto-derived note titles from content** — title is a separate field; empty title falls back to "Untitled".
8. **RAG across tasks / notes / context** — out of scope but flagged for future exploration: a future feature could retrieve related tasks or other notes as LLM context for Cleanify or for promoting richer task drafts. NOT added to the prompt or data model in this PRD.
9. **Mobile-native / responsive rework** — the existing desktop-first layout is extended.
10. **Migration tooling** — `db.create_all()` on startup handles the new `notes` table; no `migrate.py` change needed.

## Further Notes

- **Vision link (from `000_PrePRD_unified-adhd-workspace.md`):** *"streamlined, friction-free, all-in-one-place workflow/workspace that is as ADHD-friendly as possible, where everything is available in as little clicks as possible."* Notes v1 is evaluated against this bar: capture is one click; promote is one selection + one click; Cleanify is one click + one Undo (no preview-then-apply modal).
- **Grilling record.** This PRD is the output of an explicit `grilling` pass over the PrePRD's Notes decisions. All eight settled questions are reflected above; the grilling transcript lives in the conversation that produced this file. Key resolved tensions, for the implementer's reference:
  - Promote-to-task reuses the existing AI parse flow (not literal text, not a new AI code path).
  - The note is left untouched after promotion (no `source_note_id`, no inline markers).
  - The notes list is flat, ordered by `updated_at` desc, no pinning.
  - Title is a separate column; empty title is a valid stored state.
  - Row creation is deferred until first non-empty autosave.
  - Cleanify replaces content in place + persistent single-step Undo (ephemeral toast rejected as too easy to lose to a stray keystroke).
  - `AIProvider.cleanify` is a sibling method to `parse_task` (no base-class `complete()` refactor).
  - The cleanify prompt is loaded by `Config` and passed in as an argument (cleanify stays a pure, unit-testable seam).
  - Every note has a Space (NOT NULL); there is no unfiled pseudo-space.
- **Context update needed (per planner read-only rule, the `build`/`automode` agent applies these during implementation):**
  - `.opencode/context/CONTEXT.md` — extend "Actors" / "Architecture" with the Notes module (a new route, a new model, a new AI seam); add `/notes` and the new API routes to the module map.
  - `.opencode/context/topics/data-model.md` — document `Note` (new model with `space_id NOT NULL`), the deferred-persistence semantics, and the absence of `source_note_id` on `Task` (intentional).
  - `.opencode/context/topics/ai-parsing.md` — document the new `cleanify` method on `AIProvider`, the new top-level `cleanify_note_with_ai` factory, the `notes_cleanify.md` prompt file, the Space-description injection, and the explicit decision NOT to introduce a `complete()` generalization.
  - New deep-dive `.opencode/context/topics/notes.md` — created when built (not created by planner; read-only outside `.opencode/plans/**`).
  - `doc/TODO.md` — mark-complete the items this PRD subsumes (the "notes" portion of the unified-workspace vision is now scoped; Tasks-kanban, Mail remain TODO).
- **Lifecycle note:** this PRD occupies slot `001`, the first `PRD_*` file after the parent `000_PrePRD_unified-adhd-workspace.md`. When this PRD's last issue moves to DONE+archive, the implementing agent flips `Status: Aligned → Done` and moves the file to `.opencode/plans/archive/`.
