# Issue: Cleanify route + EasyMDE Cleanify/Undo toolbar button

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 004
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `004_Issue_cleanify-route-and-button.md`

## What to build

Wire the Cleanify flow end-to-end: a route that takes a note, builds the system prompt (the cached `Config.NOTES_CLEANIFY_PROMPT` + the note's Space description appended), calls `cleanify_note_with_ai`, returns `{content}` without persisting. On the frontend, an EasyMDE toolbar button replaces the editor content in place immediately, the previous content is held in a JS variable, and a persistent single-step "Undo Cleanify" button is shown until dismissed or next Cleanify. The cleaned content persists through the normal debounced-autosave `PUT` path (no special Apply step).

End-to-end behaviour:

- `POST /api/notes/<id>/cleanify` (login_required):
  1. Loads the note (404 if missing).
  2. Reads `Config.NOTES_CLEANIFY_PROMPT` (cached at startup by issue 003).
  3. Appends the note's Space's description to the system prompt in the format:
     `"\n\nNote's Space context:\nName: <space.name>\nDescription: <space.description or ''>"` (mirrors how `/api/tasks/parse` appends available spaces).
  4. Calls `cleanify_note_with_ai(note.content_markdown, system_prompt)` (from issue 002).
  5. Returns `{content: <returned text>}` (whether the cleaned text or, on graceful degradation, the original).
  6. **Does not persist** — the route doesn't write to the note. The cleaned text persists through the editor's existing debounced `PUT`-on-input autosave.
- Frontend (within the EasyMDE editor wired in issue 001):
  - "Cleanify" toolbar button click → POST to the route → on success: store current editor content in a JS variable (`previousContent`), call `editor.value(response.content)` to replace the editor in place. The existing `input` event will trigger the debounced `PUT` autosave.
  - "Undo Cleanify" toolbar button (initially hidden, shown after a Cleanify) → restores `editor.value(previousContent)` in place. Hidden again after click or after next Cleanify overwrites `previousContent`.
  - "Undo Cleanify" stays visible until explicitly clicked (dismiss) or until the next Cleanify runs (overwrites previousContent). It is NOT an ephemeral toast — persistent single-step undo per PRD decision E.
- The Cleanify button is always enabled (no selection required — Cleanify operates on the whole note).
- The Undo Cleanify button is disabled / hidden when there's no `previousContent` stored.

## First step (test-first)

RED: Write `tests/test_cleanify_route.py`:

```python
def test_cleanify_returns_cleaned_content_without_persisting(client, stub_ai_provider, sample_note):
    # stub_ai_provider.cleanify returns "cleaned"
    resp = client.post(f'/api/notes/{sample_note.id}/cleanify')
    assert resp.status_code == 200
    assert resp.get_json() == {'content': 'cleaned'}

    # And the note's content_markdown is unchanged in DB after the call
    from src.models import Note
    note = Note.query.get(sample_note.id)
    assert note.content_markdown == sample_note.content_markdown  # not persisted

def test_cleanify_injects_space_description_into_system_prompt(client, stub_ai_provider_spy, sample_note):
    # stub_ai_provider_spy.cleanify records its system_prompt argument
    client.post(f'/api/notes/{sample_note.id}/cleanify')
    captured_system_prompt = stub_ai_provider_spy.captured_system_prompt
    assert sample_note.space_rel.description in captured_system_prompt
    assert sample_note.space_rel.name in captured_system_prompt

def test_cleanify_returns_original_on_ai_failure(client, stub_ai_provider_raising, sample_note):
    # stub_ai_provider_raising.cleanify raises
    resp = client.post(f'/api/notes/{sample_note.id}/cleanify')
    assert resp.status_code == 200
    assert resp.get_json() == {'content': sample_note.content_markdown}
```

Fails because the route doesn't exist yet.

GREEN flow (one step at a time):
1. Add `POST /api/notes/<id>/cleanify` route — load note, build system prompt with Space description suffix, call `cleanify_note_with_ai`, return `{content}`. No persistence.
2. First test → green (stub returns "cleaned", note content unchanged in DB).
3. Add the Space-description-injection test → RED → green (route now appends the Space context).
4. Add the AI-failure test → RED → green (verify graceful degradation via `cleanify_note_with_ai`'s built-in try/except from issue 002).
5. Frontend: wire the "Cleanify" button's `action` callback to the POST + `editor.value()` replace. Wire the "Undo Cleanify" button to restore + hide. This is not covered by automated tests (no browser driver) — verify by manual demo.

## Acceptance criteria

- [ ] `POST /api/notes/<id>/cleanify` route exists, `login_required`, returns `{content: <string>}`.
- [ ] Route does NOT persist the cleaned content (the note's `content_markdown` in DB is unchanged after the route returns).
- [ ] Route reads `Config.NOTES_CLEANIFY_PROMPT` (cached at startup by issue 003) — no per-request file reads.
- [ ] Route appends the note's Space's name + description to the system prompt in the format specified above.
- [ ] Route calls `cleanify_note_with_ai(note.content_markdown, system_prompt)` (from issue 002).
- [ ] On AI failure (stub raises), route returns `{content: <original note content>}` (graceful degradation via `cleanify_note_with_ai`'s try/except).
- [ ] 404 when note id doesn't exist.
- [ ] Frontend "Cleanify" EasyMDE toolbar button: on click → POST → on success replaces `editor.value(response.content)` in place + stores `previousContent` + shows "Undo Cleanify".
- [ ] Frontend "Undo Cleanify" toolbar button: on click → restores `editor.value(previousContent)` + hides itself. Stays visible until clicked or until next Cleanify.
- [ ] After Cleanify replace, the editor's `input` event triggers the existing debounced `PUT`-on-autosave, persisting the cleaned text through the normal path.
- [ ] "Cleanify" button is always enabled (no selection required).
- [ ] "Undo Cleanify" is hidden / disabled when no `previousContent` is stored (e.g. on initial page load).

## Blocked by

- `001_Issue_notes-crud-and-list.md` (route lands on the Notes CRUD surface + EasyMDE editor)
- `002_Issue_ai-provider-cleanify-method.md` (`cleanify_note_with_ai` must exist)
- `003_Issue_notes-cleanify-prompt-file.md` (prompt file + Config load must exist)

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
