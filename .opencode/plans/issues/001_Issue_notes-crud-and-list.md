# Issue: Notes CRUD routes + list/editor page + deferred persistence + ChangeLog

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 001
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `001_Issue_notes-crud-and-list.md`

## What to build

A complete vertical slice: a user can land on `/notes`, pick a Space, see the list of notes for that Space (flat, `updated_at` desc), click "+", start typing, have the content autosave (debounced), and persist only after first non-empty content. The user can also open, edit, rename, and delete a note. All mutations log to `ChangeLog`.

End-to-end behaviour (visible through the HTTP API + the `/notes` page):

- `GET /api/notes?space_id=<id>` → list of note DTOs for that Space, ordered by `updated_at` desc.
- `POST /api/notes` with `{space_id, title?, content_markdown?}` → creates a row, returns the new DTO, logs `entity_type='note', action='create'` to `ChangeLog`.
- `GET /api/notes/<id>` → single note DTO.
- `PUT /api/notes/<id>` with any subset of `{title, content_markdown, space_id}` → updates, returns the new DTO, logs `action='update'`.
- `DELETE /api/notes/<id>` → 204, logs `action='delete'`.
- `/notes` server-rendered route (login_required): Space switcher (lists `GET /api/spaces`), notes list panel, EasyMDE editor panel, "+ create" affordance.
- EasyMDE editor is wired with the minimal 3-button toolbar from PRD decision L (Add-as-task / Cleanify / Undo-Cleanify buttons are scaffolded as disabled placeholders here — their actual handlers land in issues 004 and 005; this issue ships the editor itself).
- Deferred persistence: the "+" click opens an empty editor bound to the currently-selected Space, with **no row created yet**. The first debounced (~800ms) autosave with non-empty `content_markdown` (or non-empty `title`) issues `POST /api/notes`; subsequent debounced saves issue `PUT /api/notes/<id>`. Navigating away with all-empty content and no prior POST = nothing persists.
- List rows show: title (or literal "Untitled" when title is empty) + the first ~80 chars of content_markdown as a preview + the `updated_at` relative timestamp.

Per PRD decision C: `Note.space_id` is NOT NULL. Every note belongs to a Space. There is no "unfiled" pseudo-space. The "+" button inherits the currently-selected Space.

The editor toolbar's three action buttons are scaffolded here as `disabled` placeholders so the editor is demoable end-to-end without depending on issues 002/004/005. (Alternatively, leave them out entirely and add them in 004/005 — implementer's call as long as the result is a demoable editor with title + content + autosave.)

## First step (test-first)

RED: Write `tests/test_notes_crud.py`:

```python
def test_post_note_creates_row_and_changelog(client):
    # assumes a Space exists (fixture)
    resp = client.post('/api/notes', json={'space_id': 1, 'content_markdown': 'hello'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['id'] > 0
    assert body['space_id'] == 1
    assert body['content_markdown'] == 'hello'
    # GET list includes it at the top
    resp = client.get('/api/notes?space_id=1')
    assert resp.get_json()[0]['id'] == body['id']
    # ChangeLog row exists
    log = ChangeLog.query.filter_by(entity_type='note', entity_id=body['id'], action='create').first()
    assert log is not None
```

Fails because `Note` model doesn't exist, route doesn't exist. Going RED proves the path doesn't exist.

GREEN flow (one step at a time):
1. Add `Note` model to `src/models.py` with `to_dict()`.
2. Add `GET /api/notes?space_id`, `POST /api/notes` routes to `src/app.py`, with ChangeLog writers.
3. Run `pytest tests/test_notes_crud.py::test_post_note_creates_row_and_changelog` → green.
4. Add the next test (e.g. `GET /api/notes/<id>` returns the DTO; deletion returns 204 + logs delete) → RED → green.
5. Etc. (PUT, DELETE, ordering, "Untitled" fallback, 404 on missing note — one test at a time).
6. Last: build `/notes` template + the EasyMDE editor wiring + the debounced autosave + deferred-persistence client logic. The frontend is not covered by automated tests (no browser driver) — verify by manual demo.

## Acceptance criteria

- [ ] `Note` model exists with `id`, `space_id` (NOT NULL, FK→spaces.id), `title` (nullable String), `content_markdown` (Text), `created_at`, `updated_at`; `to_dict()` returns all six fields.
- [ ] `Note` table auto-creates on app startup via the existing `db.create_all()` call (no `migrate.py` change).
- [ ] All six routes exist and behave per PRD decision D, all `login_required`.
- [ ] `GET /api/notes?space_id=X` returns notes for X ordered by `updated_at` desc.
- [ ] `POST /api/notes` rejects `space_id=null` (NOT NULL column enforces it).
- [ ] `PUT /api/notes/<id>` accepts any subset of `{title, content_markdown, space_id}`.
- [ ] `DELETE /api/notes/<id>` returns 204 + logs `'delete'`.
- [ ] All three mutations write a `ChangeLog` row with `entity_type='note'` + matching action + JSON-serialized `to_dict()` snapshots.
- [ ] `/notes` server-rendered page exists with `login_required`, a Space switcher (uses `GET /api/spaces`), a notes list panel, and an editor panel.
- [ ] EasyMDE loads via CDN (matching the existing FullCalendar/SortableJS CDN pattern) with `autosave: {enabled: false}`.
- [ ] The EasyMDE toolbar is the explicit minimal custom array from PRD decision L (Add-as-task / Cleanify / Undo-Cleanify buttons present, either disabled-placeholders or omitted pending issues 004/005).
- [ ] Debounced autosave (~800ms) issues `POST` on first non-empty content, then `PUT`s on subsequent edits.
- [ ] Empty editor + navigate away = no row persisted (deferred persistence).
- [ ] List rows show title or "Untitled", plus ~80-char content preview, plus relative timestamp.
- [ ] Space switching swaps the displayed notes list (`localStorage` persists the selected Space, recalls it on next page load).

## Blocked by

- `000_Issue_test-harness-bootstrap.md`

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
