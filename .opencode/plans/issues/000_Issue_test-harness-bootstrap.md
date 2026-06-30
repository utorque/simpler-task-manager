# Issue: Test harness bootstrap + parse_task regression guard

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 000
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `000_Issue_test-harness-bootstrap.md`

## What to build

Bootstrap the project's first test harness. Today the repository has no test directory and no test runner configured — this issue creates the foundation that every subsequent issue (in this PRD and beyond) reuses.

End-to-end behaviour: running `pytest` from the repo root discovers tests under `tests/`, spins up a Flask app with an in-memory SQLite database (`db.create_all()` once per test session), and provides:

1. A Flask app fixture + test client fixture (`pytest-flask` or plain Flask test client).
2. An in-memory SQLite fixture that calls `db.create_all()` once and tears down tables between tests (or recreates the schema per test — implementer's call, as long as tests don't leak state).
3. A `StubAIProvider` subclass of `AIProvider` that returns canned responses for both `parse_task` (canned list of task dicts) and `cleanify` (canned markdown string), plus a fixture that patches `get_ai_provider()` to return the stub.
4. A regression-guard test: `parse_task_with_ai("buy milk", stub_system_prompt)` returns the canned task list when the stub provider is patched in. This test passes immediately — it anchors the invariant we promised not to break (the `parse_task` code path stays unchanged across this PRD).

The harness is intentionally minimal. It does NOT bootstrap file uploads, IMAP stubs, or browser drivers — those concerns belong to the issues that need them. The harness here covers route-layer integration tests + one unit-level seam for the AI provider.

## First step (test-first)

RED: Write `tests/test_parse_task_regression.py`:

```python
def test_parse_task_with_ai_returns_canned_response(stub_ai_provider):
    result = parse_task_with_ai("buy milk", "stub-system-prompt")
    assert result == stub_ai_provider.PARSED_TASKS_CANNED
```

This fails because `tests/conftest.py` doesn't exist, `tests/` doesn't exist, `parse_task_with_ai` can't be imported cleanly into a test, and `stub_ai_provider` fixture isn't defined. Going RED here proves the harness isn't wired yet.

GREEN flow (vertical, one step at a time rather than bulk):
1. `pip install pytest pytest-flask` (and list them in `requirements.txt`).
2. Create `tests/conftest.py` with the app fixture (in-memory SQLite, `db.create_all()`, app context push), the client fixture, the `StubAIProvider`, and the `stub_ai_provider` fixture that patches `get_ai_provider`.
3. Create `tests/test_parse_task_regression.py` — assertion as above.
4. Run `pytest` → green.

## Acceptance criteria

- [ ] `pytest` runs from repo root and discovers tests under `tests/`.
- [ ] An in-memory SQLite database is used for tests; the prod `instance/tasks.db` is **not** touched by the test run.
- [ ] `StubAIProvider` exists and is patched into the module under test so calls to `get_ai_provider()` return the stub.
- [ ] The `parse_task_with_ai(text, system_prompt)` regression test passes immediately, anchoring the invariant that `parse_task` is unchanged across this PRD.
- [ ] `requirements.txt` lists `pytest` + `pytest-flask` (or whatever test runner is chosen).
- [ ] The harness does NOT depend on any real LLM API calls (the stub returns canned text everywhere).
- [ ] Tests don't leak state across each other.

## Blocked by

None — can start immediately.

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
