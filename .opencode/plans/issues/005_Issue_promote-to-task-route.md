# Issue: Promote-to-task route + EasyMDE Add-as-task toolbar button

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 005
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `005_Issue_promote-to-task-route.md`

## What to build

Wire the promote-to-task flow end-to-end: a route that takes selected text from a note, calls the existing `parse_task_with_ai` (no new AI code path), returns a task draft DTO pre-tagged with the note's `space_id`, and opens the existing `#addTaskModal` pre-filled for the user to confirm via the existing `POST /api/tasks`. The note is left untouched.

End-to-end behaviour:

- `POST /api/notes/<id>/promote-to-task` (login_required):
  1. Loads the note (404 if missing).
  2. Reads `selected_text` from the request body.
  3. Builds the system prompt exactly as the existing `/api/tasks/parse` route does: `Config.SYSTEM_PROMPT` + the available spaces list suffix (so the LLM sees the same context it sees when the user pastes text into the AI task creator).
  4. Calls the existing `parse_task_with_ai(selected_text, system_prompt)` (unchanged signature, unchanged behaviour).
  5. For each task draft returned: if `space_id` is `None`, defaults it to the note's `space_id`. (The LLM is still free to pick a different space if it sees fit; this is a default, not an override.)
  6. Returns the task draft(s) DTO — same shape `POST /api/tasks/parse` already returns.
  7. **Does not persist a task.** The route returns a draft; the client must still POST to `/api/tasks` to create the task. The note's `content_markdown` is untouched (the call only reads `selected_text`, doesn't modify the buffer).
- Frontend (within the EasyMDE editor wired in issue 001):
  - "Add as task" toolbar button is `disabled` when the selection is empty (toggled via `editor.codemirror.on('cursorActivity', ...)` + `editor.codemirror.somethingSelected()`), enabled when the selection is non-empty.
  - On click: `editor.codemirror.getSelection()` returns the selected text → POST `{selected_text}` to the route → on success, open the existing `#addTaskModal` pre-filled with the returned draft(s), including `space_id = note.space_id`.
  - User confirms in the modal → existing `POST /api/tasks` creates the task (and writes the existing `entity_type='task', action='create'` ChangeLog entry — no special handling here, no `source_note_id`).
  - On AI failure: a clear failure toast; button becomes clickable again; editor selection is preserved (CM5 doesn't lose selection on focus shifts to a toast/button).
  - The note's content is left completely untouched — no inline markers, no strike-through, no `source_note_id` on Task (per PRD decisions G and Q3).

**Multi-task modal handling:** if the LLM returns multiple task drafts from a single selection (one of the recently-shipped features of `parse_task_with_ai`), the modal may need a small extension to handle multiple drafts. Verify against the actual `#addTaskModal` code in `index.html` at implementation time; if it currently assumes a single task per modal, either (a) iterate client-side and open the modal once per draft in sequence or (b) extend the modal to display multiple drafts. Implementation-level call, but the test below only asserts the single-draft path.

## First step (test-first)

RED: Write `tests/test_promote_to_task_route.py`:

```python
def test_promote_returns_task_draft_without_persisting(client, stub_ai_provider, sample_note):
    # stub_ai_provider.parse_task returns [{title: "buy milk", priority: 5}]
    resp = client.post(f'/api/notes/{sample_note.id}/promote-to-task',
                       json={'selected_text': 'buy milk'})
    assert resp.status_code == 200
    drafts = resp.get_json()
    assert isinstance(drafts, list)
    assert len(drafts) == 1
    assert drafts[0]['title'] == 'buy milk'

    # No Task row was created by the promote call itself
    from src.models import Task
    assert Task.query.count() == 0

    # The note's content_markdown is unchanged
    from src.models import Note
    note = Note.query.get(sample_note.id)
    assert note.content_markdown == sample_note.content_markdown

def test_promote_defaults_space_to_note_space_when_llm_returns_none(client, stub_ai_provider, sample_note):
    # stub returns a draft with space_id=None
    resp = client.post(f'/api/notes/{sample_note.id}/promote-to-task',
                       json={'selected_text': 'buy milk'})
    drafts = resp.get_json()
    assert drafts[0]['space_id'] == sample_note.space_id  # defaulted from the note

def test_promote_returns_404_for_missing_note(client, stub_ai_provider):
    resp = client.post('/api/notes/9999/promote-to-task',
                       json={'selected_text': 'buy milk'})
    assert resp.status_code == 404
```

Fails because the route doesn't exist.

GREEN flow (one step at a time):
1. Add `POST /api/notes/<id>/promote-to-task` route — load note, build system prompt (mirrors `/api/tasks/parse`), call `parse_task_with_ai`, default `space_id` to `note.space_id` when LLM returns None, return drafts.
2. First test → green (stub returns one draft, no Task in DB, note unchanged).
3. Add the space-defaulting test → RED → green.
4. Add the 404 test → RED → green.
5. Frontend: wire the "Add as task" EasyMDE toolbar button — `cursorActivity` handler to toggle disabled, `getSelection()` to read the selected text, POST, open `#addTaskModal` with the returned draft(s). Not covered by automated tests — verify by manual demo.

## Acceptance criteria

- [ ] `POST /api/notes/<id>/promote-to-task` route exists, `login_required`, accepts `{selected_text: string}`.
- [ ] Route calls the existing `parse_task_with_ai(selected_text, system_prompt)` — no new AI code path.
- [ ] Route builds the system prompt the same way `/api/tasks/parse` does (`Config.SYSTEM_PROMPT` + available spaces suffix).
- [ ] Route defaults each draft's `space_id` to `note.space_id` when the LLM returns `None` (doesn't override LLM-chosen spaces).
- [ ] Route returns the same DTO shape as `POST /api/tasks/parse`.
- [ ] Route does NOT create a `Task` row (no `POST /api/tasks` call server-side; that's the client's job via the modal).
- [ ] Route does NOT modify the note's `content_markdown` (only reads `selected_text`).
- [ ] Route returns 404 for a non-existent note id.
- [ ] Frontend "Add as task" EasyMDE toolbar button is `disabled` when editor selection is empty (toggled on `cursorActivity`).
- [ ] Frontend button click: `editor.codemirror.getSelection()` → POST → on success, opens `#addTaskModal` pre-filled with the returned draft(s), including `space_id = note.space_id`.
- [ ] User confirms in the modal → existing `POST /api/tasks` creates the task (logs `entity_type='task', action='create'` via the existing code path; no `source_note_id`).
- [ ] On AI failure, a clear failure toast is shown; button becomes clickable again; editor selection is preserved.
- [ ] No `source_note_id` column is added to `Task`; no inline markers added to the note.

## Blocked by

- `001_Issue_notes-crud-and-list.md` (route lands on the Notes CRUD surface + EasyMDE editor exists)

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
