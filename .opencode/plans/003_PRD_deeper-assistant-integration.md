# PRD — Deeper Assistant Integration

- **Status**: Implemented (2026-07-08) — issues 003.01–003.10 all DONE, archived in `issues/archive/` (each carries a closing note with deviations); context docs updated per Further Notes
- **Created**: 2026-07-08
- **Supersedes**: —
- **Related**: `002_PRD_hermes-agent-integration.md` (archived; this builds on its embedded-Chainlit replacement), `000_PrePRD_unified-adhd-workspace.md` (applied vision)

## Problem

The embedded first-party Chainlit assistant (`chat/`) is wired and working, but three gaps limit how deeply the user can actually *use* it as the project's main thinking surface:

1. **QoL friction** (Bundle A): starters fire-and-send with no chance to add context; their icons don't render reliably; the model picker (`CHAT_MODELS` env var) requires a `.env` edit + restart to add a model.
2. **Authoring & prompt opacity** (Bundle B): the base system prompt is a source file read once at import (stale across edits, clobbered by `git pull`); skills, though designed as on-disk packages, can't be created or edited from the app; there is no visibility into *what* the model sees each turn (spaces guidance, tools, skills, injected context); reasoning effort is fixed.
3. **No filesystem access** (Bundle C): the `assistant-workspace` volume (shared web ↔ sandbox) is a black box — the only way to see produced files is the auto-attach trailing block, and the model has no sanctioned URL convention to deliver a file inline, so it hallucinates URLs (`https://workspace.simpler.com/files/…`).

The user (single ADHD individual, this project's only actor) wants the assistant to be a *first-class authoring and file-working surface*, not just a chat.

## Solution shape

Three loosely-coupled workstreams, one PRD, three issue tracks (A/B/C). Shared dependencies called out in **Cross-cutting**.

### Bundle A — Assistant QoL

- **Starter icons**: drop the Lucide `icon` field; prefix the label text with an emoji char (e.g. `▶ Working on report`, `✨ Plan my day`). Unicode → always renders, no icon-font dependency.
- **Starter click = inject context + prefill composer (NOT auto-send)**:
  - Clicking a task starter fires the `/task <id>` command immediately → the `[Workspace context injected…]` system message lands in the thread (same as today).
  - AND prefills the composer with a seed (e.g. `#12 — `) the user edits, then sends.
  - Generic starters prefill their seed message verbatim (no injection).
  - `cl.Starter` has no native prefill → bridges via `chat/public/simpler-bridge.js` (listen for a custom window event from the click, set the Chainlit composer text). **Spike risk**: confirm Chainlit's composer is reachable from a custom JS event; fallback is a "click again to populate" pattern.
- **Model picker migration**: replace `@cl.set_chat_profiles` with `cl.context.emitter.set_modes` inside `on_chat_start`. Model is a `Mode` category (`id: 'model'`) with one `ModeOption` per configured model. Selected value read per-message via `msg.modes.get('model')` and passed to `run_agent(model=...)`. Persists across messages within a chat, switchable mid-conversation. Lucide icons on options.
  - Model *list* source: `instance/assistant/models.json` (Bundle B's settings panel manages it); falls back to `CHAT_MODELS` env var → `AI_MODEL` (current behavior) when the instance file is absent or empty. No restart needed once the panel writes the file.

### Bundle B — Prompt/skill authoring & prompt layering

- **System prompt storage**:
  - `chat/prompts/system.md` = immutable shipped default (git-tracked).
  - On first in-app edit (or on demand), copy to `instance/assistant/system.md` (gitignored, survives upgrades).
  - `load_system_prompt()` reads from the instance override if present, else the shipped default; called **per message** (not module-global), so edits are live.
  - "Reset to shipped" button deletes the instance override.
- **Prompt layering** (no change to the per-turn assembly structure, but the boundary is made explicit and documented):
  - **Global base** (user-editable from the app): identity, domain vocabulary, style rules, treatment-of-data rules. = the editable `system.md`.
  - **Per-concern injection** (built per message in `build_system_prompt()`, NOT editable as one blob — each piece has its own authoring surface):
    - Current date/time (already per-message).
    - Selected spaces + their `context_markdown` guidance (already per-message; edited in the Spaces destination).
    - Tools list (already per-message; driven by what's wired).
    - Skills section `## Skills` (already per-message; managed via the skills panel/agent tool).
    - `/command`-injected context blocks (already per-message, as system messages).
- **Skills authoring**:
  - Skills dir = `instance/assistant/skills/` (gitignored, survives upgrades); the shipped `chat/skills/` stays as the bundled default set and is read-only. `chat/skills.py::skills_dir()` resolution: instance dir first (read+write), shipped dir second (read-only fallback) — both listed in the skills panel, shipped ones marked "bundled"/non-deletable.
  - **Agent tool** `create_skill(name, description, body, files=None)`: writes `instance/assistant/skills/<name>/SKILL.md` (+ optional bundled files). The model drafts skills on the user's request; the user can then edit in-app.
  - **In-app form** (in the Assistant settings panel, Bundle B): list (with bundled/instance badge + delete on instance-only), create (name/description/body markdown), edit (full markdown editor). Persisted to the instance skills dir.
  - **Dovetail with Bundle C** (later): the `WorkspaceView` file browser (Bundle C) is designed to serve multiple roots; when extended to the skills dir, the user manages skill files directly through the file UI. Not in this PRD's scope; the blueprint's multi-root design accommodates it.
- **Assistant settings panel** (right of the subheader, next to the current space-filter chips; opens as a panel/modal, NOT a shell-wide destination):
  - **Model**: manage the editable model list (add/remove/reorder) persisted to `instance/assistant/models.json`. Feeds the `model` Mode picker (Bundle A).
  - **Modes management**: define Mode categories (`model`, `reasoning`) and their options; create/delete a mode; assign which models appear under `model`. The `reasoning` Mode category (e.g. `low/medium/high`) is defined here and surfaced as a second chat-bar picker (see below).
  - **Composition viewer**: read-only stacked card list of what's pinned into the system prompt right now — base prompt (name + last-modified), spaces guidance source (selected space names), tools list (names), skills list (names), current date. Optionally expandable to show the full assembled prompt text (read-only).
  - **Skills manager**: list/create/edit/delete (as above).
  - **Prompt editor**: button opening a full-screen markdown editor for `instance/assistant/system.md`, with a "Reset to shipped" button that deletes the override.
- **Reasoning effort as a second Mode**: `cl.context.emitter.set_modes([model_mode, reasoning_mode])` in `on_chat_start`. Both appear as pickers in the Chainlit chat bar, switchable mid-chat. Selected value read per-message via `msg.modes.get('reasoning')`, passed to the provider as the reasoning-effort parameter (provider-specific mapping in `chat/providers.py`).

### Bundle C — Workspace filesystem sidebar

- **New Flask blueprint** `/api/workspace/*` (registered in `src/app.py`, same process; auth = the existing `login_required`):
  - `GET /api/workspace/tree?root=<root>&path=<rel>` → JSON file/folder listing (name, type, size, mtime).
  - `POST /api/workspace/mkdir` `{root, path}`.
  - `POST /api/workspace/upload` `{root, path, file}` (multipart, chunked for large).
  - `GET /api/workspace/files/<root>/<path:rest>` → file download (with proper Content-Type/Disposition; **this is the URL the model emits inline**).
  - `PUT /api/workspace/file` `{root, path, content}` → save text (md editor).
  - `DELETE /api/workspace/file?root=<root>&path=<rel>`.
  - `POST /api/workspace/move` `{root, from, to}`.
  - **Multi-root design**: `root` maps to a named, allowlisted list of mounted dirs: `{workspace: settings.files_dir(), skills: instance/assistant/skills}` (skills root added later, blueprint-ready now). Path traversal protection via `os.path.realpath` + prefix check.
- **`WorkspaceView` sidebar** (`src/static/js/workspace.js`, following `notes.js`/`mail.js` conventions):
  - Assistant-only right sidebar, ~1/5 width, togglable (button in the Assistant tab subheader + a shortcut).
  - Tree view (folders expand/collapse), breadcrumb, drag-drop upload (file or folder), create folder, create/edit `.md` inline (EasyMDE, already a dep — reuse the notes editor), download, delete, move (drag within tree).
  - Reads from `/api/workspace/tree?root=workspace`.
  - Persists open/closed + last-path in localStorage.
- **Model file delivery**:
  - **DROP** the current auto-attach-after-turn behavior (`files.new_files_since` trailing `📁 Files from this turn:` block in `on_message`). Rationale: the model legitimately creates scratch files during a turn; surfacing all of them is noise.
  - **ADD** a native assistant tool `attach_file_to_answer(path: str)` (in `chat/files.py`): creates a Chainlit `cl.File` element pointing at `/workspace/<path>`, queued and sent at the end of the model's turn. Rich download chip with name/size.
  - **ADD** inline download links: the system prompt documents the URL convention `/api/workspace/files/workspace/<rel>`. The model emits relative markdown links like `[download report](/api/workspace/files/workspace/reports/report.pdf)` inline in its reply; they render as clickable same-origin downloads in the chat (no model-side tool call needed).
  - Model uses **either** the tool (rich chip) **or** inline links (clickable text), based on context.

## Cross-cutting

- **`/api/workspace/*` blueprint** (Bundle C) is the shared dependency for: the sidebar view, the model's inline download links, and the future "manage skills via file browser" enhancement (Bundle B dovetail). Build it first within Bundle C.
- **`instance/assistant/`** is the new gitignored home for: `system.md` (Bundle B), `models.json` (Bundle A/B), `skills/` (Bundle B). Settings panel writes here; no DB schema change (avoid coupling to the app-DB migration story).
- **Assistant settings panel (Bundle B) vs workspace sidebar (Bundle C)**: both are "right-side" surfaces in the Assistant tab — they must NOT collide. Settings opens as a modal/overlay (transient); workspace is a persistent right drawer (toggle open/closed). Specify this in the issues.
- **`simpler-bridge.js`** (Bundle A starter prefill) + **`simper.css`** (Bundle C sidebar styling) are the frontend touch points; keep them consistent with the shell's existing vanilla-JS / no-build-step conventions.
- **Tests**: the existing pytest harness in `tests/` covers route-layer integration (`tests/test_routes*.py`), the assistant suite (`tests/test_chat_*`), the MCP tool suite, and the scheduler. New routes (workspace blueprint), new assistant tool (`attach_file_to_answer`, `create_skill`), and the new starter/model-picker behaviors all get TDD coverage there. The `StubAIProvider` + `SimpleNamespace` patterns from existing assistant tests are the seam for the agent-tool tests.

## Non-goals

- No multi-user / no per-user settings (single-user app, `instance/` is global).
- No file search / full-text index in the workspace sidebar (basic tree + rename + delete only).
- No file preview for non-text formats in the sidebar (download only; text/md edits inline).
- No backfill of the model-picker migration: existing chat threads stay on whatever `chat_profile` they were created with; new chats use Modes. No data migration.
- No DB schema changes (`instance/assistant/` is files-on-disk only).
- No mobile-specific sidebar layout (desktop-first; sidebar collapses on narrow screens but no mobile UX polish).
- Bundled skills (`chat/skills/`) stay read-only; the user copies them to instance to edit (no "duplicate to instance" button in v1 — they recreate or use the agent).
- No "reasoning effort" UI for models that don't support it (provider-side no-op; the picker still shows but the value is ignored by providers without the param).

## Risks & dependencies

- **Chainlit composer prefill** (Bundle A): `cl.Starter` has no native prefill API. Spiking the composer-set-text path via `simpler-bridge.js` is the first concrete step of that issue; if it proves unreachable, fall back to a "prefill via clipboard + toast" or "click twice" UX. Flagged as the issue's spike gate.
- **Modes API stability** (Bundle A/B): Modes is a newer Chainlit feature than Chat Profiles; the API (`set_modes`, `msg.modes.get`) is confirmed in the docs but the issue must verify against the installed Chainlit version and pin a minimum version if needed.
- **Reasoning-effort provider mapping** (Bundle B): `chat/providers.py` currently emits OpenAI/Anthropic wire formats with no reasoning param; adding the param needs provider-specific mapping (`reasoning_effort` on OpenAI, `thinking` on Anthropic) and graceful no-op for endpoints that reject unknown params. Issue must handle the rejection case.
- **Path traversal** (Bundle C): the `/api/workspace/files/<path>` route is the highest-risk surface — a path-traversal bug exposes any file the app can read. Must use `os.path.realpath` + allowlist-prefix check, fuzzed in tests.
- **`instance/assistant/` creation** (Bundle A/B/C): all three write there; the first issue to touch it must create the dir tree + `.gitignore` entry, and the others depend on it existing. Sequence as a shared-issue dependency.

## Further Notes

- **Context update needed**: `.opencode/context/topics/chat-assistant.md` — update the Model picker section (Profiles → Modes, instance/assistant/models.json source), the Skills section (instance-scoped skills dir + create_skill tool + in-app form), the Starters section (emoji labels, prefill-not-send), the Workspace section (add: `/api/workspace/*` blueprint, WorkspaceView sidebar, attach_file_to_answer tool, dropped auto-attach). The `build`/`automode` agent picks this up during implementation.
- **Context update needed**: `.opencode/context/CONTEXT.md` — add `instance/assistant/` to the data-model mention, add `src/routes/workspace.py` + `src/static/js/workspace.js` to the module map, note the Mode-picker + reasoning-emission in the assistant description.
- **Shortcuts convention**: a new shortcut for the workspace sidebar toggle must be added to the `#helpModal` table in `templates/index.html` (the single source of truth for shortcuts).
