# AI Task Parsing

> `src/ai_parser.py` + `src/prompt.md`. Generic provider abstraction around OpenAI-compatible and Anthropic APIs.

## Provider abstraction
- `AIProvider` base: `__init__(api_key, base_url, model)` + `parse_task(text, system_prompt) -> List[Dict]`.
- `OpenAIProvider` — works for **any OpenAI-compatible endpoint** (OpenAI, Mistral, Infomaniak). Configured via `AI_API_BASE_URL` (default `https://api.openai.com/v1/`) and `AI_MODEL` (default `gpt-3.5-turbo`). Uses raw `requests.post` (not the `openai` SDK) against `{base_url}/chat/completions`.
- `AnthropicProvider` — native Anthropic API when `AI_API_BASE_URL` points at `api.anthropic.com`.
- `get_ai_provider(api_key, base_url, model)` — factory selecting impl by URL heuristics.

## Entry point
`parse_task_with_ai(text, ...)` (called from `app.py` `/api/tasks/parse`):
1. Build provider via `get_ai_provider` using `Config.AI_API_KEY/BASE_URL/MODEL`.
2. Send `text` + `Config.SYSTEM_PROMPT` (loaded once from `src/prompt.md` at startup).
3. `_process_response(response_text)` — strips ` ```json ` / ` ``` ` fences, `json.loads`; accepts **either a single dict or a list of dicts** (multi-task parsing is supported). Each task dict's relative `deadline` ("tomorrow", "next week", "next monday", …) is normalized to an absolute datetime via `datetime.now()`.
4. Returns `List[Dict]` — caller persists each as a `Task`.

## Config / env
- `AI_API_KEY` (preferred) — falls back to legacy `ANTHROPIC_API_KEY` if unset (see `doc/README.md`).
- `AI_API_BASE_URL` — e.g. `https://api.mistral.ai/v1/`, `https://api.anthropic.com/`.
- `AI_MODEL` — e.g. `mistral-small`, `claude-haiku-4-5`, `gpt-3.5-turbo`.
- `SYSTEM_PROMPT` — read from `src/prompt.md` once in `config.py:load_system_prompt()`; missing file falls back to a minimal default string.

## Caveats
- `prompt.md` is the **formatting contract** for the LLM's JSON output — editing it can break `_process_response`'s parsing assumptions. Treat prompt + parser as a pair.
- `openai` SDK is in `requirements.txt` but the OpenAI-compatible provider path uses raw `requests`; the SDK is pulled in for type/compat only.
- Deadline normalization handles a fixed set of English relative phrases — new languages or phrasings need added branches in `_process_response`.
