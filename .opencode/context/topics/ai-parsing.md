# AI Task Parsing + Note Cleanify + Email-to-Task

> `src/ai_parser.py` + `src/prompts/task_creation.md` (task parsing) + `src/prompts/notes_cleanify.md` (note tidying) + `src/prompts/email_to_task.md` (email-to-task). Generic provider abstraction around OpenAI-compatible and Anthropic APIs. Prompt-context assembly (available-spaces block, per-space guidance, space hint) is centralized in `src/prompt_context.py` (`spaces_context()`, `space_guidance_block()`, `build_task_parse_prompt()`, `build_email_to_task_prompt()`).

## Provider abstraction
- `AIProvider` base: `__init__(api_key, base_url, model)` + `parse_task(text, system_prompt) -> List[Dict]`.
- `OpenAIProvider` — works for **any OpenAI-compatible endpoint** (OpenAI, Mistral, Infomaniak). Configured via `AI_API_BASE_URL` (default `https://api.openai.com/v1/`) and `AI_MODEL` (default `gpt-3.5-turbo`). Uses raw `requests.post` (not the `openai` SDK) against `{base_url}/chat/completions`.
- `AnthropicProvider` — native Anthropic API when `AI_API_BASE_URL` points at `api.anthropic.com`.
- `get_ai_provider(api_key, base_url, model)` — factory selecting impl by URL heuristics.

## Entry point
`parse_task_with_ai(text, ...)` (called from `routes/tasks.py` `/api/tasks/parse` and `routes/notes.py` promote-to-task):
1. Build provider via `get_ai_provider` using `Config.AI_API_KEY/BASE_URL/MODEL`.
2. Send `text` + `Config.SYSTEM_PROMPT` (loaded once from `src/prompts/task_creation.md` at startup).
3. `_process_response(response_text)` — strips ` ```json ` / ` ``` ` fences, `json.loads`; accepts **either a single dict or a list of dicts** (multi-task parsing is supported). Each task dict's relative `deadline` ("tomorrow", "next week", "next monday", …) is normalized to an absolute datetime via `datetime.now()`.
4. Returns `List[Dict]` — caller persists each as a `Task`.

## Config / env
- `AI_API_KEY` (preferred) — falls back to legacy `ANTHROPIC_API_KEY` if unset (see `doc/README.md`).
- `AI_API_BASE_URL` — e.g. `https://api.mistral.ai/v1/`, `https://api.anthropic.com/`.
- `AI_MODEL` — e.g. `mistral-small`, `claude-haiku-4-5`, `gpt-3.5-turbo`.
- `SYSTEM_PROMPT` — read from `src/prompts/task_creation.md` once in `config.py:load_system_prompt()`; missing file falls back to a minimal default string.

## Space guidance block (guide, not source)
- `Space.context_markdown` (user-edited in the Spaces destination) is appended to EVERY task-drafting prompt by `prompt_context.space_guidance_block()`: a `--- SPACE CONTEXT (guidance only) ---` section listing each non-empty space context, preceded by explicit framing that it steers decisions (space choice, priority, deadline, duration, wording) and is NOT part of the user's request — never to be copied into task fields or used as a task source.
- Empty when no space has context, so baseline prompts are byte-identical to pre-feature ones. Cleanify does NOT get the block (it's a task-drafting concern).
- `build_email_to_task_prompt()` mirrors `build_task_parse_prompt()` (EMAIL_TO_TASK_PROMPT + spaces list + guidance); the mailboxes route uses it instead of assembling inline.

## restrict_space vs space_hint (PRD 001 — hard scope vs soft hint)
- `build_task_parse_prompt(space_hint=None, restrict_space=None)`, `spaces_context(restrict_space=None)`, and `space_guidance_block(restrict_space=None)` each take an optional **`restrict_space`**: a Space id (int) or name (str, case-insensitive). When it **resolves** to one Space, the "Available spaces" block lists ONLY that space and the guidance block includes ONLY its `context_markdown` — a **hard single-space scope**. When it is `None` (the default), omitted, or does not resolve to any space (logs a warning, no 500), all spaces are listed — byte-identical to pre-feature prompts.
- `restrict_space` (hard scope) is **independent of** `space_hint` (soft hint). `space_hint` appends an `IMPORTANT: assign to '<name>' unless the user specifies otherwise` line; `restrict_space` instead removes the other spaces from the prompt entirely. The kanban AI inline-create path uses `restrict_space` (hard) — it does NOT use `space_hint`. The header quick-capture path keeps its `space_hint` soft-hint behaviour, unchanged.
- `/api/tasks/parse` accepts two new optional JSON fields: `restrict_space` (passed through to the prompt builder) and `force_status` (a status string; when present and a member of `TASK_STATUSES` it is applied via `task.apply_status()` AFTER `db.session.flush()` and BEFORE `record_change('create', ..., actor='ai')`, so the audit `new` snapshot reflects the final column placement and only one create row is written — `actor` stays `'ai'` because the task is AI-drafted; the status override is deterministic client placement, not a user-authored edit). An invalid `force_status` returns 400 and creates nothing (validated before the AI call). Both fields are optional and absent ⇒ byte-for-byte the legacy quick-capture behaviour.

## Caveats
- `task_creation.md` is the **formatting contract** for the LLM's JSON output — editing it can break `_process_response`'s parsing assumptions. Treat prompt + parser as a pair.
- `openai` SDK is in `requirements.txt` but the OpenAI-compatible provider path uses raw `requests`; the SDK is pulled in for type/compat only.
- Deadline normalization handles a fixed set of English relative phrases — new languages or phrasings need added branches in `_process_response`.

## Note Cleanify seam (separate from task parsing)
- `AIProvider.cleanify(self, note_text: str, system_prompt: str) -> str` — a SIBLING method to `parse_task` on the base class + both concrete providers (`OpenAIProvider`, `AnthropicProvider`). It mirrors `parse_task`'s HTTP setup (headers, endpoint, model selection) but returns the **raw model text** — no `_process_response` JSON extraction. Structural duplication between `cleanify` and `parse_task` within each provider is accepted and preferred over a base-class `complete()` generalization (PRD `001` decision F — explicitly rejected for blast-radius reasons; do NOT introduce `complete()`).
- Top-level factory `cleanify_note_with_ai(note_text, system_prompt) -> str` in `src/ai_parser.py` calls `get_ai_provider().cleanify(...)` and **gracefully degrades**: on any exception OR empty/None response it returns the input `note_text` unchanged (no exception escapes the caller). This is the one-true entry point the Cleanify route (`POST /api/notes/<id>/cleanify`) uses.
- `parse_task` (base + both providers) and `parse_task_with_ai` are **unchanged** in signature and behaviour — the `tests/test_parse_task_regression.py` test (issue 000) anchors this invariant.
- `Config.NOTES_CLEANIFY_PROMPT` — loaded once at startup from `src/prompts/notes_cleanify.md` (`config.py:load_notes_cleanify_prompt()`, sibling to the existing `load_system_prompt()`). Missing file falls back to a default non-empty string. The Cleanify route appends the note's Space context — `"\n\nNote's Space context:\nName: <space.name>\nDescription: <space.description or ''>"` (read via `note.space_rel`) — mirroring how `/api/tasks/parse` appends the available-spaces list.
- The `notes_cleanify.md` prompt is a minimalistic tidying contract (tidy punctuation / line+paragraph breaks / list formatting; preserve the user's wording and intent verbatim where clear; leave unclear sections unchanged rather than guessing; never invent facts / summarize away specifics / convert bullets to prose / rename entities). It is a SYSTEM prompt and does NOT mention spaces.
- Promote-to-task (`POST /api/notes/<id>/promote-to-task`) does NOT add a new AI code path — it reuses `parse_task_with_ai(selected_text, system_prompt)` with the system prompt built via `prompt_context.build_task_parse_prompt()` (same as `/api/tasks/parse`). Drafts returned with `space_id is None` default to the note's `space_id`; the route persists nothing (the client opens the shared `TaskDraftModal`, then `POST /api/tasks` does the actual create + logs `entity_type='task', action='create'`).

## Email-to-task seam (Mail module, same reuse pattern as promote-to-task)
- `email_to_task_with_ai(subject, body, system_prompt) -> List[Dict]` in `src/ai_parser.py` — **reuses the `parse_task` provider seam** (user message = `"Subject: <subject>\n\n<body>"`); no new provider method, consistent with the no-`complete()` decision. Graceful degradation: on any exception or empty response it returns a single trivial draft (`title = subject`, `description = body[:500]`, priority 5).
- `Config.EMAIL_TO_TASK_PROMPT` — loaded once at startup from `src/prompts/email_to_task.md` (`load_email_to_task_prompt()`, sibling loaders pattern; missing file → default string). The mailboxes route builds the full prompt via `prompt_context.build_email_to_task_prompt()` (spaces list + space guidance).
- The route (`POST /api/mailboxes/<id>/messages/<uid>/add-task`) pre-tags drafts with the mailbox's `space_id` when the LLM returned none, and persists NOTHING — the client confirms via the shared `TaskDraftModal` → `POST /api/tasks`. ChangeLog: the confirmed create logs as `entity_type='task', action='create'`.
- Actor convention: tasks created through `/api/tasks/parse` log `actor='ai'` in ChangeLog; drafts confirmed by the user through `POST /api/tasks` log `actor='user'` (the human made the final call).
