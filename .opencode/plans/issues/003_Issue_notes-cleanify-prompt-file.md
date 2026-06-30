# Issue: notes_cleanify.md prompt file + Config load

<!-- Kanban status — update as work progresses: TODO | DOING | DONE | BLOCKED <one-line reason> | CANCELLED -->
**Status:** TODO

- **ID**: 003
- **Parent PRD**: `001_PRD_notes.md`
- **File**: `003_Issue_notes-cleanify-prompt-file.md`

## What to build

Author the minimalistic Cleanify system prompt file and wire `Config` to load it once at startup. This issue is purely the prompt-text contract + the Config load; the route that consumes the prompt lives in issue 004.

End-to-end behaviour:

- `src/prompts/notes_cleanify.md` exists and contains the minimalistic tidying prompt described below.
- `Config.NOTES_CLEANIFY_PROMPT` is a non-empty string loaded once at app startup (sibling to the existing `Config.SYSTEM_PROMPT`), cached on the `Config` object.
- No per-request file reads happen on the hot path — the prompt is loaded at startup and cached.

**Prompt authoring contract (from PRD decision H, verbatim):**

The `notes_cleanify.md` prompt MUST be minimalistic. It makes the note more readable but NEVER changes anything that MAY alter the meaning. Better to leave something unchanged than to assert something not clear.

Specifically, the prompt must direct the LLM to (this is a floor, not a ceiling — the author may add constraints that further reduce meaning-alteration risk, but not weaken these):

- Tidy punctuation (commas, periods, capitalization at sentence starts).
- Normalize line breaks and paragraph breaks.
- Normalize list formatting (consistent bullet characters, consistent indentation).
- Preserve the user's wording and intent verbatim where the intent is clear.

The prompt must NOT, at minimum:

- Invent facts not present in the input.
- Summarize away specifics (no "in short" / "to summarize" that loses information).
- Change bullet points into prose that loses information.
- Rename entities (people, places, project names, etc.).
- Restate sections in the prompt's own words when the user's wording is clear.

If the input's intent is unclear, the prompt MUST instruct the LLM to leave that section unchanged rather than guessing. "Better to leave something unchanged than to assert something not clear."

The prompt is a system prompt: it sets behaviour for the LLM, not the user. It will be paired with a user message that is the note's content. The Space's description will be appended to it by the route handler (issue 004), so the prompt itself does NOT need to mention spaces — leave that to the route-level injection.

## First step (test-first)

RED: Write `tests/test_cleanify_prompt_loaded.py`:

```python
def test_notes_cleanify_prompt_loaded_at_startup(app):
    # app is the test app fixture
    prompt = app.config['NOTES_CLEANIFY_PROMPT']
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    # and the source file exists
    import os
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'prompts', 'notes_cleanify.md')
    assert os.path.exists(prompt_path)
```

Fails because `notes_cleanify.md` doesn't exist and `Config.NOTES_CLEANIFY_PROMPT` isn't set yet.

GREEN flow:
1. Create `src/prompts/notes_cleanify.md` with the minimalistic prompt per the contract above.
2. Extend `src/config.py` to load `src/prompts/notes_cleanify.md` once at startup into `Config.NOTES_CLEANIFY_PROMPT` (mirror the existing `load_system_prompt()` pattern for `prompt.md`).
3. `pytest tests/test_cleanify_prompt_loaded.py::test_notes_cleanify_prompt_loaded_at_startup` → green.

## Acceptance criteria

- [ ] `src/prompts/notes_cleanify.md` exists and contains the minimalistic tidying prompt.
- [ ] The prompt explicitly instructs the LLM to tidy punctuation, normalize line breaks/paragraph breaks, normalize list formatting, AND preserve the user's wording and intent verbatim where intent is clear.
- [ ] The prompt explicitly instructs the LLM NOT to invent facts, summarize away specifics, convert bullets to prose that loses information, rename entities, or restate clear sections in the prompt's own words.
- [ ] The prompt explicitly instructs the LLM to leave unclear sections unchanged rather than guessing ("better to leave something unchanged than to assert something not clear").
- [ ] The prompt is a system prompt and does NOT mention spaces (the route handler appends the Space description separately in issue 004).
- [ ] `Config.NOTES_CLEANIFY_PROMPT` is a non-empty string loaded once at startup.
- [ ] The prompt is loaded at startup and cached on `Config`; no per-request file reads.
- [ ] `src/prompt.md` (the existing task-parsing prompt) is untouched; its `Config.SYSTEM_PROMPT` load path is unchanged.

## Blocked by

None — can start immediately. (Logically independent of issue 000's harness bootstrap in terms of the prompt file itself, but the test for it needs the harness, so the test is blocked by 000. The prompt file can be authored in parallel.)

## Close-out

Tick before `Status → DONE` (unconditional gate — see [context-hygiene.md](../../instructions/context-hygiene.md)):

- [ ] `.opencode/context/` refreshed via `/refresh-context-md`
