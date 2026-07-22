# PRD 001 — Kanban AI-inline-create & inline priority editing

Status: Done
Created: 2026-07-02
Owner: —

## 1. Problem / Why

Two small friction points in the Tasks board (kanban) subview, both ADHD-relevant (every extra click/context switch is a tax):

1. **Kanban inline-create bypasses AI.** The `+` in a column header opens an inline input; on Enter it POSTs raw `{title, status, space_id}` to `/api/tasks` directly. A user typing `"call Marie tomorrow 3pm about the report"` in the `work` column gets a task literally titled that, with no parsed deadline, priority, or duration, no AI cleanup. Meanwhile the header quick-capture routes the same text through `/api/tasks/parse` and gets a properly-structured task. Same input text → inconsistent task quality depending on which input field it was typed into. That asymmetry is a frequent source of "why is this task missing a deadline / ugly".
2. **Priority can only be edited via the full edit modal.** The board-card shows a priority badge (`board-card-priority`), but clicking the *card* opens the edit modal; the badge itself is non-interactive. Adjusting a task's urgency by one notch is a modal → number field → save round trip. For an ADHD workspace this should be one click + one keystroke.

## 2. Goals / Non-goals

### Goals
- **G1** — Kanban inline-create (`+` → Enter) routes the entered text through `/api/tasks/parse`, so the same AI parsing used by quick-capture applies (title cleanup, deadline parsing, duration/priority inference, multi-task split).
- **G2** — When a specific space filter is active on the board, the AI prompt is scoped to that one space only (not the hint-the-AI soft constraint used elsewhere — a hard restriction of the "Available spaces" + "Space guidance" blocks to that single space).
- **G3** — The column the user created in is respected: a task typed in the `doing` column lands in `doing`, not `todo`, regardless of what the AI returns.
- **G4** — Clicking the `board-card-priority` badge turns it into an inline number editor (current value pre-selected); typing a number overrides it (clamped 0–10); ↑/↓ increment/decrement by 1 (clamped); Enter commits via `PUT /api/tasks/<id> {priority}` and exits edit mode.
- **G5** — Single round-trip for AI inline-create (no extra `PUT` to fix the column status).

### Non-goals
- Inline priority editing on the **Overview** subview (`space-task-priority`) — out of scope; board cards only.
- Changing the header quick-capture flow or the per-space "add task" modal flow — untouched.
- Re-architecting `parse_task_with_ai` or merging `parse_message` / `cleanify` — not touching the AI provider abstraction.
- Confirm-modal for AI inline-create — these auto-persist just like quick-capture (no `TaskDraftModal`). Kanban inline-create has always auto-created; preserving that keyboard-speed expectation matters more than draft-confirm safety here.
- Per-space AI restriction for the header quick-capture `space_hint` path — unchanged (that path keeps passing all spaces + a soft hint).

## 3. User stories

- **US1** — As a user with the board filtered to the `work` space, I click `+` on a column, type `"call Marie tomorrow 3pm about the report"`, press Enter → I get one AI-cleaned task with a parsed deadline of tomorrow 3pm, tagged to `work`, landing in the column I typed it in.
- **US2** — As a user with the board set to "All spaces", I click `+` on the `doing` column, type a task, press Enter → the AI parses it with access to all spaces (exactly like header quick-capture), and the resulting task lands in `doing`.
- **US3** — As a user looking at a board card showing priority `7`, I click the `7` badge → it becomes an editable input with `7` selected; I press ↑ → shows `8`; I press Enter → the task's priority becomes `8` and the badge returns to display mode showing `8`.
- **US4** — As a user editing the priority inline, I type `42` → it shows/clamps to `10`; I press Enter → priority is saved as `10`.
- **US5** — As a user editing the priority inline, I press Esc → the editor closes, priority reverts, nothing is persisted.
- **US6** — As a user editing the priority inline, I click elsewhere (blur) → the editor closes, priority reverts, nothing is persisted. (Enter is the only commit; this prevents accidental commits and matches "press Enter to set".)

## 4. Functional requirements

### 4.1 Kanban AI inline-create (G1–G3, G5)

**Frontend** (`src/static/js/app.js`, the `.board-inline-add input` keydown handler around line 419):
- On Enter (after the existing trim/empty guard), instead of POSTing `/api/tasks`, POST `/api/tasks/parse` with body:
  - `text`: the trimmed input value
  - `force_status`: `form.dataset.status` (the column's status)
  - `restrict_space`: `boardSpaceFilter` (the active board space filter) **when it is non-null**; omitted entirely when `boardSpaceFilter === null`.
- Keep the existing UX on success: clear input, keep the form open ("stays open for rapid entry"), call `loadTasks()`. Re-render the board so the new task(s) appear in the right column.
- On non-ok response: keep the input value, show `showAlert(error.error || 'Error creating task', 'danger')` — same pattern as quick-capture. Do **not** silently fall back to direct `/api/tasks` creation (the AI parser already degrades gracefully server-side via `parse_task_with_ai`'s no-key fallback).

**Backend** — `routes/tasks.py` `parse_task()` endpoint:
- Accept two new optional JSON fields: `restrict_space` (a space id or name) and `force_status` (a status string).
- Pass `restrict_space` through to `build_task_parse_prompt(restrict_space=...)` (new param, see 4.2).
- After each task is created (post-`db.session.flush()`), if `force_status` is present and valid (member of `TASK_STATUSES`), call `task.apply_status(force_status)` **before** `record_change('create', ...)` so the audit snapshot reflects the final status. This satisfies G3 + G5 in one request.
- `actor` stays `'ai'` (the task was AI-drafted). The status override is a deterministic placement decision by the client, not a user-authored edit — keep the single `create` audit row, actor `'ai'`.
- Backward compat: when `restrict_space` / `force_status` are absent, current quick-capture behavior is byte-for-byte unchanged.

### 4.2 Single-space prompt scoping (G2)

**Backend** — `src/prompt_context.py`:
- `spaces_context()` and `space_guidance_block()` each gain an optional `restrict_space` parameter (a space id — int — or a space name — str, resolved via a case-insensitive/flexible match; prefer id).
  - When set and resolves to one `Space`: the "Available spaces" block lists **only** that space; the space-guidance block includes **only** that space's `context_markdown`.
  - When set but does not resolve (no such space): treat as unset (fall through to all-spaces) and log a warning. Do not 500.
- `build_task_parse_prompt(space_hint=None, restrict_space=None)` threads `restrict_space` into both helpers.
- The existing `space_hint` soft-constraint path is kept separate and unchanged. For kanban AI inline-create we use `restrict_space` (hard scope), **not** `space_hint` (soft hint). The two are independent and can coexist on the same call if ever needed.

### 4.3 Inline priority editing (G4)

**Frontend** (`src/static/js/app.js`, `renderBoardCard` + a new click/key handler):
- The `board-card-priority` badge gets a click handler that:
  - `e.stopPropagation()` — must **not** trigger the card's open-edit-modal click, nor the board multi-select Alt-click path (the multi-select guard already keys on Alt; a plain click on the badge is not Alt, so just stopPropagation).
  - Replaces the badge's text content with a number `<input type="number" min="0" max="10">` seeded with the current `task.priority`, selects its contents.
  - Focuses the input.
- Input keydown handler:
  - `Enter` → commit: clamp the parsed integer to `[0,10]` (NaN → revert/abort), `PUT /api/tasks/<id> {priority: clampedValue}`, on ok `loadTasks()` (re-render closes the editor), on error `showAlert` + revert.
  - `Escape` → revert: restore the badge text, discard the input, no request.
  - `ArrowUp` → `preventDefault`, set input value to `min(10, current+1)`. Do **not** commit on arrow (commit is Enter only); just updates the displayed number awaiting commit.
  - `ArrowDown` → `preventDefault`, set input value to `max(0, current-1)`.
  - Typed digits → standard number input behaviour; clamp on commit, not on each keystroke (simpler + matches "if I type above 10 it's set to 10").
- Input `blur` → revert (same as Escape). Enter/blur must remove the input before any async `loadTasks`, otherwise the editor lingers.
- While the input is focused, the global keyboard-shortcut handlers (`1`–`5`, `/`, `S`, `?`) must not fire. The existing `initKeyboardShortcuts()` already skips `INPUT`/`TEXTAREA` targets — verify the priority input falls under that guard; if it uses `type="number"` it is still an `INPUT` and is covered.
- Editing is available only on the **board (kanban)** card priority badge (`board-card-priority`). The Overview subview's `space-task-priority` is untouched.

### 4.4 Clamping & validation specifics

- Priority clamp boundaries: `0 ≤ value ≤ 10`, integer. `parseInt` with radix 10; `NaN` → revert (no commit, no server call).
- `force_status` validation: must be in `TASK_STATUSES`; if an invalid value arrives at the endpoint, return `400` with the same shape as the existing `update_task` status-error response (reuse the message format).
- `restrict_space` that doesn't resolve: server logs, proceeds with all-spaces (no client-visible error).

## 5. Technical approach / touched files

- `src/prompt_context.py` — add `restrict_space` param to `spaces_context`, `space_guidance_block`, `build_task_parse_prompt`.
- `src/routes/tasks.py` — `parse_task()` reads `restrict_space` + `force_status`; applies `force_status` via `apply_status` before audit; passes `restrict_space` to prompt builder.
- `src/static/js/app.js` — inline-create handler swaps `/api/tasks` → `/api/tasks/parse` with new body fields; new `board-card-priority` click → inline `<input>` editor with the keydown/blur behaviour above; `stopPropagation` on the badge click.
- `tests/` — new/extended tests (see §7).

No DB schema change. No new endpoints. No new models.

## 6. Edge cases & decisions log

| Case | Decision |
|---|---|
| Inline-create with "All spaces" filter | Behave exactly like header quick-capture: full spaces list in prompt, `restrict_space` omitted. |
| Inline-create in a non-`todo` column | `force_status` overrides the AI/default `todo`; task lands in the typed column. |
| AI returns multiple tasks from one inline-create | Each gets `force_status` applied; all land in the column; `loadTasks()` re-renders. Rapid-entry form stays open. |
| AI parse fails / no key configured | `parse_task_with_ai` already degrades to simple parsing; endpoint still 201s. Client shows success. No fallback to raw `/api/tasks`. |
| Priority input typed `42` | Clamps to `10` **on commit**, not per keystroke. |
| Priority input cleared / non-numeric | `NaN` → revert, no commit, no server call. |
| Priority edit + global shortcut (e.g. `2` for Notes) while editing | Skipped by the existing INPUT-target guard in `initKeyboardShortcuts()`. Verify, don't assume. |
| Priority badge click while card is part of board multi-select set | Plain click (no Alt) → stopPropagation prevents the Alt-toggle path entirely; it just opens the editor. Acceptable — editing priority of a multi-selected card was never a feature. |
| `restrict_space` value doesn't match any space | Fall back to all-spaces silently (server warning log). |
| Blur during an in-flight `PUT` | Guard: on Enter, detach the input synchronously then await the request; ignore subsequent blur. Prevents double-submit. |

## 7. Tests (TDD — features start red)

### 7.1 Kanban AI inline-create
- **T1** (route-layer, `tests/test_tasks.py` or sibling): `POST /api/tasks/parse` with `{text, restrict_space: <id>, force_status: 'doing'}` using a `StubAIProvider` returning one task → response 201, task landed with `status='doing'`, `actor='ai'` in the most recent ChangeLog row, and the prompt used by the stub captured only the restricted space (assert via a prompt-spy or by checking the stub received a system_prompt containing the restricted space's name and **not** containing other spaces' names).
- **T2**: same call with `force_status='bogus'` → 400, no task created.
- **T3**: same call omitting `restrict_space` → prompt contains all spaces (existing quick-capture behaviour preserved — regression guard).
- **T4**: same call with `restrict_space=<nonexistent>` → 201, prompt contains all spaces (silent fallback).
- **T5**: multi-task stub response (2 tasks) with `force_status='blocked'` → both created, both `status='blocked'`, single `loadTasks` re-render path verified client-side via a JS test or by contract (response is a list).

### 7.2 Prompt scoping (`tests/test_prompt_context.py` — new or extended)
- **T6**: `build_task_parse_prompt(restrict_space=<space_id>)` produces a system_prompt whose "Available spaces" block lists exactly one space (the restricted one) and whose space-guidance block contains only that space's `context_markdown`.
- **T7**: `build_task_parse_prompt(restrict_space=<name>)` (string match) behaves identically to id.
- **T8**: `build_task_parse_prompt()` with no restrict — all spaces present (regression).
- **T9**: `build_task_parse_prompt(restrict_space=None)` == all-spaces (explicit None == omitted).

### 7.3 Inline priority editing
- Frontend behaviour is JS; if a JS test harness exists, add one for the input lifecycle. If no JS test harness exists, cover the **server** side (priority clamp + audit) and document the client interactions as a manual checklist issue:
  - **T10** (route-layer, regression guard — already likely exists): `PUT /api/tasks/<id> {priority: 8}` updates priority, writes audit row actor `'user'`. If absent, add it.
  - **T11** (route-layer): `PUT {priority: 42}` — current endpoint does **not** clamp (it stores 42). Decide: either (a) clamp server-side at the `update_task` seam (preferred, gives US4 guarantee regardless of caller), or (b) clamp only client-side. **Recommendation: (a)** — add server-side clamp `[0,10]` in `update_task` for `priority`, returning the clamped value in the response. Add test `PUT {priority: 42}` → response priority is `10`; `PUT {priority: -3}` → `0`. *(This widens G4 correctness to all callers, not just the new badge editor.)*

## 8. Rollout

Single PR, fully backward-compatible (new optional fields; existing callers unchanged). No migration. No config change. No deploy sequencing.

## 9. Further notes / context hygiene

- Context update needed: `.opencode/context/topics/ai-parsing.md` — document the new `restrict_space` (single-space hard scope) vs `space_hint` (soft hint) distinction on `build_task_parse_prompt`, and that `/api/tasks/parse` now accepts `force_status` + `restrict_space`.
- Context update needed: `.opencode/context/topics/` (whichever covers the board / shortcuts) — document the inline priority-edit interaction and that the `board-card-priority` badge is now interactive (click → edit). Update the "Shortcuts help modal = single source of truth" note: **no new keyboard shortcut is added** (the badge is click, not a shortcut key), so the `#helpModal` table does **not** need a new row; but the existing card-click convention paragraph in `CONTEXT.md` (click=edit, Ctrl+click=done, Shift+click=freeze) should note that clicking the priority badge is an exception (it edits priority, not opens the modal) — flag this for the build agent to add to the relevant context doc.
- The `Status ⇆ completed` invariant is unaffected: `apply_status('doing')` keeps `completed` in sync; `apply_status('done')` stamps `completed_at`. No new invariant.
