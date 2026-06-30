# Issue: AIProvider.cleanify method + cleanify_note_with_ai factory

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 002
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `002_Issue_ai-provider-cleanify-method.md`

## What to build

Add a new `cleanify` method to the `AIProvider` base class and to both concrete providers (`OpenAIProvider`, `AnthropicProvider`), plus a top-level `cleanify_note_with_ai(note_text, system_prompt) -> str` factory that mirrors the existing `parse_task_with_ai` factory pattern. This issue adds the AI seam; the route that consumes it lives in issue 004.

End-to-end behaviour (verifiable at the AI-provider level, no HTTP route needed here):

- `get_ai_provider().cleanify(note_text, system_prompt)` returns a string of LLM-tidied markdown for OpenAI-compatible endpoints and Anthropic endpoints.
- `cleanify_note_with_ai(note_text, system_prompt)` calls `get_ai_provider().cleanify(...)`.
- On any exception or empty response, `cleanify_note_with_ai` returns the input `note_text` unchanged (graceful degradation — no exception escapes to the caller).
- The `parse_task` code path on `AIProvider`, both concrete providers, and the top-level `parse_task_with_ai` factory are **unchanged** in signature and behaviour. The existing `parse_task_with_ai` regression test (issue 000) continues to pass.

PRD constraints (from decision F):
- `cleanify` mirrors `parse_task`'s HTTP setup (headers, endpoint, model selection via `get_ai_provider()` URL heuristics) but returns raw model text rather than extracting a JSON list of task dicts. No JSON parsing is performed on the response.
- Some structural duplication between `cleanify` and `parse_task` within each concrete provider (similar request boilerplate, different prompt slot + different response shape) is accepted and preferred over a base-class `complete()` refactor (which the user explicitly rejected for blast-radius reasons).

## First step (test-first)

RED: Write `tests/test_cleanify_ai_seam.py`:

```python
def test_cleanify_note_with_ai_returns_canned_text(stub_ai_provider):
    # stub_ai_provider.cleanify returns "cleaned"
    result = cleanify_note_with_ai("messy text", "stub-system-prompt")
    assert result == "cleaned"

def test_cleanify_note_with_ai_returns_input_on_error(stub_ai_provider_raising):
    # stub_ai_provider_raising.cleanify raises Exception
    result = cleanify_note_with_ai("messy text", "stub-system-prompt")
    assert result == "messy text"  # graceful degradation: input returned unchanged

def test_parse_task_with_ai_still_works(stub_ai_provider):
    # regression — must remain unchanged
    result = parse_task_with_ai("buy milk", "stub-system-prompt")
    assert result == stub_ai_provider.PARSED_TASKS_CANNED
```

Fails because `cleanify` method doesn't exist on `AIProvider` and `cleanify_note_with_ai` isn't a module-level symbol in `ai_parser.py` yet.

GREEN flow (one step at a time):
1. Add `cleanify(self, note_text, system_prompt) -> str` abstract method on the `AIProvider` base class.
2. Implement on `OpenAIProvider` (mirror `parse_task`'s HTTP setup; return raw `response.json()['choices'][0]['message']['content']` or equivalent — no JSON extraction).
3. Add `cleanify_note_with_ai(note_text, system_prompt) -> str` top-level function with try/except → return `note_text` on any exception.
4. `pytest tests/test_cleanify_ai_seam.py::test_cleanify_note_with_ai_returns_canned_text` → green (stub returns canned).
5. Add the second test (raising stub → graceful degradation) → RED → green.
6. Add the third regression test (parse_task still works) — should already pass; it's a guard.

## Acceptance criteria

- [ ] `AIProvider` base class has `cleanify(self, note_text: str, system_prompt: str) -> str` (abstract or with a NotImplementedError body matching the existing pattern).
- [ ] `OpenAIProvider` implements `cleanify` returning raw LLM text (no JSON parsing).
- [ ] `AnthropicProvider` implements `cleanify` returning raw LLM text (no JSON parsing).
- [ ] Top-level `cleanify_note_with_ai(note_text, system_prompt) -> str` exists in `src/ai_parser.py` and calls `get_ai_provider().cleanify(...)`.
- [ ] `cleanify_note_with_ai` catches all exceptions and empty responses, returning the input `note_text` unchanged in those cases.
- [ ] `parse_task` on the base class, both concrete providers, and the top-level `parse_task_with_ai` factory are unchanged in signature and behaviour (issue 000's regression test still passes).
- [ ] No new dependencies are added (uses existing HTTP libraries already in `requirements.txt`).
- [ ] The unit tests use `StubAIProvider` (the stub from issue 000 will need extending with a `cleanify` method returning canned text; do this in this issue or in the harness — implementer's call, as long as the tests pass).

## Blocked by

- `000_Issue_test-harness-bootstrap.md`

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
