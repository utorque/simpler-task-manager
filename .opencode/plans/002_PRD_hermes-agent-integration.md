# PRD 002 — Hermes Agent Integration (MCP server + embedded Hermes destination)

> **Status**: Proposal / analysis (no code yet). Written 2026-07-05.
> **Goal**: Connect [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research's open-source personal agent) to Simpler so that (a) a conversational agent with persistent memory can create, query, schedule and reason over tasks/notes/spaces/mail with full app context, (b) Hermes lives **inside the unified shell as its own destination page** (like Tasks/Notes/Mail/Calendar/Spaces), and (c) Hermes's cron/automation abilities can run recurring workflows (daily brief, inbox sweep, weekly review) against the app.
> **One-line architecture**: Simpler exposes its domain as an **MCP server** (sidecar, wrapping the existing REST API with a new bearer-token auth mode); Hermes consumes it as an MCP client; the UI gains a 6th destination that embeds a Hermes chat surface (iframe'd `hermes-webui` behind a header-rewriting reverse proxy, or a native chat pane speaking to Hermes's OpenAI-compatible API server — both specced below).

---

## 1. What Hermes Agent is (research summary, 2026-07)

Hermes Agent — released by Nous Research in February 2026, MIT-licensed, `github.com/NousResearch/hermes-agent` — is a self-hosted, provider-agnostic autonomous agent. Everything below was verified against the official docs (`hermes-agent.nousresearch.com/docs/…`, source in the repo under `website/docs/`).

Capabilities relevant to this integration:

- **Persistent memory** — user-profile modeling (Honcho), agent-curated memory files (`MEMORY.md`, `USER.md`), FTS5 full-text session search with LLM summarization for cross-session recall. The agent genuinely accumulates context about the user over time — exactly the "one big agent with full context" the product wants.
- **Skills** — when it solves a problem it can write a reusable skill document (agentskills.io-compatible, stored under `~/.hermes/skills/`). We can also hand-author skills (e.g. "how to plan my week in Simpler").
- **MCP client** — connects to any MCP server (stdio subprocess or remote HTTP/SSE), configured in `~/.hermes/config.yaml` under `mcp_servers:`, with per-server tool allow/deny lists. This is the sanctioned way to give Hermes external tools. Managed interactively via `hermes mcp` / the dashboard.
- **Cron / Jobs** — built-in natural-language cron scheduler with delivery to any connected platform ("daily reports, nightly backups, weekly audits… running unattended"), plus a REST **Jobs API** (`/api/jobs` CRUD, pause/resume/run-now).
- **Messaging gateway** — one `hermes gateway` process routes Telegram, Discord, Slack, WhatsApp, Signal, Email and CLI; voice transcription; shared slash commands (`/new`, `/model`, `/skills`, …). So the same agent that has our MCP tools is reachable from the phone.
- **OpenAI-compatible API server** — enabled with `API_SERVER_ENABLED=true` + `API_SERVER_KEY=…` in `~/.hermes/.env`; listens on `127.0.0.1:8642`. Exposes:
  - `POST /v1/chat/completions` (stateless, SSE streaming, `hermes.tool.progress` custom events),
  - `POST /v1/responses` (**server-side conversation state** — chain turns via `previous_response_id` or a named `"conversation"`; 100-response LRU),
  - **Runs API** (`/v1/runs`, `/v1/runs/{id}/events` SSE, `/stop`, `/approval` for human-in-the-loop tool gating),
  - **Jobs API** (see above), **Sessions API** (`/api/sessions*` CRUD, fork, `/chat`, `/chat/stream`),
  - `GET /v1/models`, `/v1/capabilities`, `/v1/skills`, `/v1/toolsets`,
  - Bearer auth with `API_SERVER_KEY`; CORS **disabled by default** (`API_SERVER_CORS_ORIGINS` to open it); `X-Hermes-Session-Key` header gives a stable per-channel memory scope.
  - Any OpenAI-format frontend works against it (Open WebUI, LobeChat, LibreChat, … or our own vanilla-JS pane).
- **Web surfaces** (this answers "does a Hermes web UI exist?" — yes, two):
  1. **Official dashboard** — `hermes dashboard` → `http://127.0.0.1:9119`. Admin panel (config editor, API keys, MCP servers, skills, cron, sessions, logs/analytics, gateway health) **plus a Chat tab** that embeds the real Hermes TUI in the browser via xterm.js (needs the `.[web,pty]` extras + Node). Auth gate (password / Nous-Portal OAuth / self-hosted OIDC) engages automatically on non-loopback binds; reverse-proxy aware (`X-Forwarded-*`, `HERMES_DASHBOARD_PUBLIC_URL`). **Explicitly not iframe-embeddable** — CORS restricted to localhost origins, admin-grade surface.
  2. **`hermes-webui`** (community, `github.com/nesquena/hermes-webui`) — a **chat-first** three-panel web UI (sessions sidebar / chat / workspace file browser), mobile-friendly. Python 3.11 stdlib HTTP server + **vanilla JS, no build step** (same philosophy as Simpler). Docker deploy on port 8787. Runs the Hermes agent **in-process** against the same `HERMES_HOME` state the CLI uses (optional `HERMES_WEBUI_CHAT_BACKEND=gateway` mode). Auth: none on localhost; optional password (`HERMES_WEBUI_PASSWORD`), WebAuthn passkeys, native OIDC; signed HMAC HTTP-only cookies. Caveats for embedding (§4.2): it sets `X-Frame-Options` on all responses and has **no base-path/subpath support**.
- **Model-agnostic** — Nous Portal, OpenRouter, OpenAI, Anthropic, local endpoints; switch with `hermes model`. Install: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`.

Docs index (all under `https://hermes-agent.nousresearch.com/docs/`): `user-guide/features/mcp`, `reference/mcp-config-reference`, `guides/use-mcp-with-hermes`, `user-guide/features/api-server`, `user-guide/features/web-dashboard`, `user-guide/features/cron`, `user-guide/features/skills`, `user-guide/features/memory`, `user-guide/messaging`, `user-guide/security`, `developer-guide/architecture`.

**Ruled out early**: Hermes's *relay connector contract* (`docs/relay-connector-contract.md` in their repo) — the protocol for adding a new chat *platform* to the gateway (WebSocket `/relay`, HMAC bearer, `CapabilityDescriptor`/`MessageEvent` envelopes). Building a "Simpler connector" so the app becomes a first-class Hermes messaging platform is possible but is a Node/TypeScript adapter with cryptographic/identity obligations — heavy, and the API server (above) gives us the same outcome for a fraction of the work. Not pursued.

---

## 2. Integration architecture overview

Three pillars, deliberately decoupled so each ships independently:

```
┌────────────────────────────── user's server (docker network) ──────────────────────────────┐
│                                                                                              │
│  ┌ Simpler (Flask, :53000) ┐        ┌ simpler-mcp (sidecar, :8765) ┐      ┌ Hermes host ┐   │
│  │ REST API  /api/*         │◄──────│ FastMCP (streamable HTTP)    │◄─────│ hermes       │   │
│  │ + Bearer API_TOKEN auth  │ REST  │ tools = wrapped REST calls   │ MCP  │  gateway     │   │
│  │ + /#hermes destination   │       └──────────────────────────────┘      │  (+API :8642)│   │
│  │   (6th page in shell)    │◄───────────────── OpenAI-compat / iframe ───│  webui :8787 │   │
│  └───────────────────────────┘                                            └──────────────┘   │
│         ▲ reverse proxy (Caddy/nginx): app.example.com + hermes.example.com                  │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Pillar A — `simpler-mcp`**: an MCP server exposing Simpler's domain (tasks, subtasks, spaces, notes, schedule, mail-read, changelog) as typed tools. Hermes registers it in `config.yaml`. (§3)
2. **Pillar B — the Hermes destination**: a 6th page in the unified shell (`#hermes`, shortcut `6`) embedding a chat surface. Two variants specced; recommendation in §4.3. (§4)
3. **Pillar C — automations**: Hermes cron jobs / Jobs API driving recurring workflows through the MCP tools, delivered to Telegram/etc. or surfaced in-app. (§5)

A fourth idea from the original brief — routing Simpler's *internal* AI features (quick-capture parse, Cleanify, email-to-task, auto-doing) through the MCP server / through Hermes — is analyzed in §6 with a "mostly no, with one cheap experiment" recommendation.

---

## 3. Pillar A — the Simpler MCP server

### 3.1 Placement decision: sidecar wrapping the REST API (chosen)

| Option | Verdict | Why |
|---|---|---|
| **A. Sidecar process wrapping the REST API** (FastMCP calls `http://web:53000/api/*`) | ✅ **chosen** | Reuses every existing route behavior: validation, the status⇔completed invariant, subtask two-way sync, `audit.record_change()` single-transaction seam, Fernet handling, graceful AI degradation. Zero duplicated business logic; the 122-test suite keeps guarding the semantics. Deployable/killable independently of the app. |
| B. Sidecar importing `src/models.py` directly (shared SQLite file) | ❌ | Two writer processes on one SQLite file (the app runs without WAL today); bypasses route-level invariants unless re-implemented; couples the MCP server to the ORM internals. |
| C. Mount MCP inside Flask itself | ❌ | The official `mcp` Python SDK's streamable-HTTP transport is ASGI (Starlette); Flask is WSGI. Bridging (`WsgiToAsgi`/dispatcher middleware or a second in-process server thread) is possible but adds a foreign runtime to the app for no functional gain over A. Revisit only if ops burden of a second container proves annoying. |
| D. No MCP at all — hand Hermes an API token + a *skill* document teaching it to `curl` the REST API | ⚠️ viable MVP | Zero new code (Hermes has a terminal tool). Great for a weekend proof-of-life. But: untyped, no tool-level allow/deny filtering, every call burns agent turns composing curl, and secrets sit in a skill file. Fine as **Phase 0 validation**, not the end state. |
| E. Auto-generate MCP from an OpenAPI spec | ❌ for now | Simpler has no OpenAPI spec; writing one just to generate tools is more work than hand-writing ~20 FastMCP functions, and generated tool descriptions are exactly the part worth hand-crafting for agent ergonomics. |

### 3.2 Prerequisite app change: bearer-token auth mode

All `/api/*` routes are gated by `@login_required` (session cookie from `POST /login`). A machine client needs a non-interactive credential:

- New env var **`API_TOKEN`** (unset ⇒ feature off, behavior byte-identical to today).
- `src/auth.py::login_required` additionally accepts `Authorization: Bearer <API_TOKEN>` (constant-time compare, `hmac.compare_digest`). No new user model — same single-user trust domain as `APP_PASSWORD`.
- Optional hardening (recommended, cheap): a second var `API_TOKEN_SCOPES` is **not** worth it — scope enforcement belongs in MCP tool filtering (§3.5) and Hermes-side `tools.include/exclude`; keep the Flask change minimal.
- Tests: token accepted / wrong token 401 / no token still cookie-gated / feature-off unchanged.

### 3.3 The MCP server itself

- **Stack**: Python 3.11, official `mcp` SDK (`pip install "mcp[cli]"`), FastMCP API, **streamable HTTP** transport (Hermes supports `url:` servers natively; stdio would force Hermes and the app onto the same host/venv). Lives in this repo at `mcp_server/` (own `requirements.txt`, own Dockerfile stage) so tool descriptions evolve with the API in one commit.
- **Config**: `SIMPLER_BASE_URL` (default `http://web:53000`), `SIMPLER_API_TOKEN`, `MCP_BIND` (default `0.0.0.0:8765` inside the docker network only — never publish this port on the host unless Hermes runs elsewhere, then front it with the reverse proxy + TLS + the same bearer token).
- **docker-compose** addition:

```yaml
  mcp:
    build:
      context: .
      dockerfile: mcp_server/Dockerfile
    environment:
      SIMPLER_BASE_URL: http://web:53000
      SIMPLER_API_TOKEN: ${API_TOKEN}
    depends_on: [web]
    restart: unless-stopped
    # expose 8765 on the docker network; publish only if Hermes is off-host:
    # ports: ["127.0.0.1:8765:8765"]
```

- **Hermes-side registration** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  simpler:
    url: "http://<docker-host>:8765/mcp"   # or https://mcp.example.com/mcp via reverse proxy
    headers:
      Authorization: "Bearer ${SIMPLER_MCP_TOKEN}"
    timeout: 60
    tools:
      resources: false
      prompts: false
      # start read-only, then widen (see rollout §7):
      # include: [list_tasks, get_task, list_spaces, get_schedule_overview, list_notes, get_note, list_changelog]
```

Tools register in Hermes as `mcp_simpler_<tool>`; verify with `hermes mcp test simpler` and `/reload-mcp`.

### 3.4 Tool surface (v1)

Design rules: tools mirror **user intents**, not raw REST (agents do better with `move_task(status=…)` than `PUT /api/tasks/<id>` field soup); every mutation returns the full updated entity; every description states units/enums (priority 0–10 higher=urgent, duration minutes, `todo/doing/blocked/done`, day 0=Monday); all timestamps ISO-8601; IDs are ints.

| Tool | Wraps | Notes |
|---|---|---|
| `list_tasks(include_completed=False, space=None, status=None)` | `GET /api/tasks` (+client-side filter) | The workhorse; returns tasks with embedded subtasks. |
| `get_task(task_id)` | `GET /api/tasks` filtered | |
| `create_task(title, description?, space?, priority?, deadline?, estimated_duration?, status?, subtasks?)` | `POST /api/tasks` | **Deterministic** create — the agent already did the "parsing". Space accepted by name or id (resolve via `list_spaces`). |
| `draft_tasks_from_text(text, space_hint?)` | `POST /api/tasks/parse` | Optional convenience reusing the in-app parser (logs `actor='ai'`). Keep OUT of v1 `include` list — Hermes composing `create_task` itself is the point (§6). |
| `update_task(task_id, …any field…)` | `PUT /api/tasks/<id>` | Status⇔completed sync and subtask auto-check ride the route for free. |
| `move_task(task_id, status)` | `PUT /api/tasks/<id>` | Sugar; enum-validated. |
| `delete_task(task_id)` | `DELETE /api/tasks/<id>` | Destructive — keep behind Hermes tool-approval or exclude initially. |
| `add_subtask(task_id, title)` / `set_subtask(subtask_id, done?, title?)` / `delete_subtask(subtask_id)` | subtask routes | Returns full parent (two-way status sync included). |
| `toggle_freeze(task_id)` / `freeze_day(date)` | freeze routes | |
| `run_schedule(task_ids?)` | `POST /api/schedule` | "Plan my day." |
| `get_calendar(days=7)` | `GET /api/external-events` + scheduled tasks | Read-only merged agenda view — the single most useful context tool for "what does my week look like". |
| `list_spaces()` / `update_space_context(space_id, context_markdown)` | spaces routes | Space AI-context editing lets the user tune per-space guidance conversationally. Space create/delete: exclude v1. |
| `list_notes(space?)` / `get_note(note_id)` / `create_note(space, title?, content_markdown?)` / `append_to_note(note_id, markdown)` | notes routes | `append_to_note` = read-modify-write via `PUT` (agents love appending logs/journals). Cleanify not exposed (in-editor UX concern). |
| `list_mail(mailbox?, limit=20)` / `read_mail(mailbox_id, uid)` | mailbox message routes | **Read-only**; passwords never leave the app (API never returns them). ⚠️ Prompt-injection surface — see §8. |
| `email_to_task_draft(mailbox_id, uid)` | `add-task` route | Returns drafts; agent then confirms with the user and calls `create_task`. Preserves the "AI drafts are never silently persisted" product rule at the conversation level. |
| `list_changelog(limit=50)` | `GET /api/logs` | Lets Hermes answer "what changed today / what did you do while I was away", and is the seed for preference learning. |

**MCP prompts/resources**: skip in v1 (Hermes registers them as utility tools; our value is in tools). One exception worth adding cheaply: a `get_workspace_summary()` tool returning counts + today's schedule + overdue list in one call — agents call it at conversation start instead of five list calls.

### 3.5 Actor attribution & audit

- Mutations arriving via the bearer token should be attributable. Cleanest: the Flask auth layer sets `g.actor = 'agent'` when bearer-authenticated, and `audit.record_change()` (single seam — one-line change) uses it as the default actor. `ChangeLog.actor` is a free string column, so `'agent'` needs **no migration**; the existing `'user'/'ai'` values are untouched.
- This gives the Overview/logs a truthful record of what Hermes did, and keeps the ChangeLog viable as preference-learning training data (`user` corrections of `agent` actions are the gold signal).

---

## 4. Pillar B — the Hermes destination (the 6th page)

Product requirement (the heart of the ask): **a "Hermes" destination in the unified shell, sitting next to Tasks/Notes/Mail/Calendar/Spaces** — nav tab, `#hermes` deep link, shortcut `6`, no page reload. Two implementation variants; both keep the shell contract.

### 4.1 Shell integration (common to both variants)

Touchpoints (all existing conventions from `.opencode/context/CONTEXT.md`):
- `templates/index.html`: new nav tab + new destination `<section id="destination-hermes">`; **update the `#helpModal` shortcuts table** (hard rule: it's the single source of truth) — `6` = Hermes.
- `static/js/app.js`: register the destination in `switchDestination`, hash routing (`#hermes`), lazy init (like `NotesView`/`MailView` — `hermes.js` module, loaded on first switch), last-destination memory keeps working via the existing mechanism.
- Keyboard: `6` switches; inputs inside the chat pane must stop propagation so typing "6" in chat doesn't navigate (same guard the quick-capture input already uses).

### 4.2 Variant 1 — embed `hermes-webui` in an iframe (fastest full-featured path)

The user's stated preference. `hermes-webui` is a complete, maintained chat UI (sessions, streaming, mobile) whose stack (stdlib Python + vanilla JS, no build) is philosophically identical to Simpler's. We embed it rather than rebuild it.

**Blockers found in research, and their resolutions:**

1. **`X-Frame-Options` on all responses** (value undocumented; DENY or SAMEORIGIN either way blocks cross-origin framing). → Resolve at the **reverse proxy**: strip `X-Frame-Options` and set `Content-Security-Policy: frame-ancestors https://app.example.com` on the hermes-webui vhost. This is strictly better than removing protection: framing is re-allowed for exactly one origin. (If any response also carries its own CSP with `frame-ancestors`, override that header at the proxy too.)
2. **No subpath support** → serve it on a **sibling subdomain**, not a path: `app.example.com` (Simpler) + `hermes.example.com` (webui). No path rewriting, absolute URLs keep working.
3. **Auth is separate** (Simpler's `APP_PASSWORD` cookie doesn't cover the webui). Options, pick one:
   - simplest: enable `HERMES_WEBUI_PASSWORD`, user logs in once inside the frame (24h HMAC cookie; must be `SameSite=None; Secure` to survive iframing — verify in Phase 2 spike, patch upstream if needed);
   - cleaner: front `hermes.example.com` with proxy-level auth (Caddy `basic_auth`, Authelia, oauth2-proxy) and leave webui auth off;
   - nicest long-term: OIDC on both apps.
4. **WebSockets/SSE through the proxy**: enable `HERMES_WEBUI_SSE_CHUNKED` if streaming stalls behind the proxy; allow the extra origins via `HERMES_WEBUI_CSP_CONNECT_EXTRA` if console shows CSP connect-src violations.

**Caddy example** (drop-in; nginx equivalent is `proxy_hide_header X-Frame-Options; add_header Content-Security-Policy "frame-ancestors https://app.example.com";`):

```caddy
app.example.com {
    reverse_proxy localhost:53000
}
hermes.example.com {
    reverse_proxy localhost:8787 {
        header_down -X-Frame-Options
        header_down Content-Security-Policy "frame-ancestors https://app.example.com"
    }
}
```

**In the shell**, the destination is then just:

```html
<section id="destination-hermes" class="destination d-none">
  <iframe src="https://hermes.example.com" id="hermes-frame"
          style="width:100%;height:calc(100vh - <header-height>px);border:0"
          allow="clipboard-write"></iframe>
</section>
```

with the iframe `src` configurable (new env `HERMES_WEBUI_URL` → injected into the template; tab hidden entirely when unset, so vanilla installs see no change). Lazy-set `src` on first switch so the frame doesn't load for users who never open it.

**Deploying hermes-webui itself** (its documented path): `git clone https://github.com/nesquena/hermes-webui && cd hermes-webui && cp .env.docker.example .env && docker compose up -d` → `:8787`. It runs the agent **in-process** against `HERMES_HOME`, sharing state (sessions, memory, skills, `config.yaml` incl. our `mcp_servers.simpler` entry) with the CLI/gateway. Run it on the same host as `hermes gateway`, or point it at the gateway with `HERMES_WEBUI_CHAT_BACKEND=gateway`.

- ✅ Full Hermes UX (session history, streaming, file browser, model switch) for ~zero UI code; upstream maintains it.
- ⚠️ Risks: double login (mitigations above); visual mismatch with Bootstrap shell (webui has a theme/skin system — acceptable); upstream changes to its header/auth behavior can break the embed (pin a release tag); iframe ↔ shell keyboard-shortcut boundary (`6` won't escape the iframe once focused — acceptable, Esc/click-outside returns focus).

### 4.3 Variant 2 — native chat pane over Hermes's OpenAI-compatible API server

Build a minimal `hermes.js` chat view (message list + input + streaming render), matching the app's Bootstrap look, wired **through a Flask proxy blueprint** (`src/routes/hermes.py`):

- `POST /api/hermes/chat` → forwards to `http://<hermes-host>:8642/v1/responses` with `Authorization: Bearer ${HERMES_API_KEY}` (server-side env; **the browser never sees the key**, and CORS on the Hermes side stays closed). Use the Responses API's named-conversation state (`"conversation": "simpler-webchat"`) so the server keeps history — no client-side transcript management. Send `X-Hermes-Session-Key: simpler-webchat` for stable long-term memory scope. Stream SSE through the proxy (Flask `stream_with_context` generator).
- Config: `HERMES_API_URL`, `HERMES_API_KEY` (both unset ⇒ tab hidden). Hermes side: `API_SERVER_ENABLED=true`, `API_SERVER_KEY=…` in `~/.hermes/.env`, then `hermes gateway`.
- ✅ Seamless single-auth, on-brand, one origin, no reverse-proxy surgery; the proxy route is also the natural place for later in-app agent affordances ("ask Hermes about this task" buttons, draft-confirm modals reusing `task_draft_modal.js`).
- ⚠️ Costs: we own a chat UI (streaming markdown, tool-progress display via the `hermes.tool.progress` events, error states); no session browser (the Responses API stores only 100 responses LRU — fine for a companion pane, not an archive; the full history still lives in Hermes's own session store, browsable from webui/dashboard).

### 4.4 Recommendation

**Do Variant 1 first** (it's the user's explicit wish and mostly ops work: subdomain + 4 proxy lines + one iframe section), **keep Variant 2 as the v2 evolution** once deeper in-app hooks (per-task "ask Hermes" actions, draft confirmations) justify owning a pane. The two are not exclusive — the Flask proxy blueprint from Variant 2 is also what automations/status surfacing will use, so it can land quietly whenever Pillar C needs it. The fallback if iframing fights back (cookie/CSP edge cases): a header nav item opening `hermes.example.com` in a new tab — one line, zero risk, ships day one alongside the spike.

---

## 5. Pillar C — automations

All of these are **Hermes-side configuration** (natural-language cron via chat, or `POST /api/jobs`), needing zero Simpler code once Pillar A exists:

- **Morning brief** (cron 07:30 → Telegram/webchat): `get_workspace_summary` + `get_calendar(1)` + overdue `list_tasks` → "here's your day; want me to `run_schedule`?"
- **Inbox sweep** (cron, per mailbox): `list_mail` new-since-last-run → for actionable mails, `email_to_task_draft` → message the user the drafts for confirmation (drafts-never-silently-persisted, preserved conversationally).
- **Weekly review** (Sunday evening): `list_changelog` + done-tasks recap, propose next-week priorities, offer `update_space_context` tweaks it learned (e.g. "you keep moving study tasks to evenings — shall I note that in the study space context?").
- **Stale-task nudge**: tasks in `doing`/`blocked` untouched > N days → ask, move, or split into subtasks.
- **Deadline sentinel** (daily): tasks whose deadline is unmeetable per current schedule (unscheduled + due soon) → warn early.

Human-in-the-loop: Hermes's approval mechanisms (dashboard approvals queue; Runs API `/approval`) plus our conservative tool `include` list keep destructive actions gated until trust is earned.

---

## 6. Should Simpler's internal AI features route through the MCP server / Hermes? (the refactor question)

Short answer: **no for the structured one-shot features, with one cheap experiment worth running.**

Analysis:
- **MCP direction fallacy**: MCP is how *agents call tools*. Quick-capture parse, Cleanify, email-to-task and auto-doing are *backend→LLM one-shot completions* with strict output contracts (`task_creation.md` is a formatting contract paired with `_process_response`). Routing them "through the MCP server" would invert the arrow for no benefit — the MCP server would just call the same `ai_parser.py` code. Nothing is gained; a network hop and a dependency are added.
- **Replacing them with Hermes calls**: because Hermes's API server is OpenAI-compatible, there is a **zero-refactor experiment**: point `AI_API_BASE_URL=http://<hermes-host>:8642/v1` + `AI_API_KEY=$API_SERVER_KEY` and the existing `OpenAIProvider` talks to Hermes unchanged. The parses would then benefit from Hermes's memory/persona. **Expected verdict: keep it off for parsing** — an agent turn is slower (it may run tools), less deterministic (chatty output can break the JSON contract), and quick-capture's whole point is sub-second friction-free capture. Worth one afternoon of testing to confirm, then documenting the result here. The features' graceful-degradation design also means the app must keep working when Hermes is down — direct provider calls preserve that.
- **Where Hermes genuinely replaces prompting**: *conversational* task creation. In chat, Hermes doesn't need `parse_task` at all — it reads the same spaces context via `list_spaces`, reasons in-conversation, and calls the **deterministic** `create_task`. That's why `draft_tasks_from_text` stays out of the v1 include list: the agent path and the quick-capture path stay parallel, both writing through the same audited routes.
- **Space guidance convergence** (do this): `Space.context_markdown` currently steers only in-app prompts. Expose it to Hermes (`list_spaces` returns it) and state in the tool description that it is guidance-not-source — the same guide-not-source framing `prompt_context.space_guidance_block()` uses. One source of per-space truth steering both AI systems.
- **Keep rejected decisions rejected**: no `AIProvider.complete()` unification (PRD 001 decision F stands); the seams (`parse_task`, `cleanify` sibling) are untouched by this whole integration.

---

## 7. Rollout plan

| Phase | Scope | Deliverables | Exit criteria |
|---|---|---|---|
| **0 — Proof of life** (no code) | Install Hermes on the server (`install.sh`), connect Telegram via `hermes gateway setup`, hand it a *temporary* API token + a hand-written skill doc teaching the REST API (option D). | Working "create a task for tomorrow" from Telegram. | Confirms end-to-end value before any engineering. Revoke the skill/token at Phase 1. |
| **1 — MCP foundation** | `API_TOKEN` bearer auth in `auth.py` (+tests); `mcp_server/` FastMCP sidecar, **read-only tools only** (`list_tasks`, `get_task`, `list_spaces`, `list_notes`, `get_note`, `get_calendar`, `get_workspace_summary`, `list_changelog`); compose service; Hermes `config.yaml` entry with `include` allowlist. | Hermes answers "what's on my plate?" correctly from any platform. | `hermes mcp test simpler` green; no mutation possible. |
| **2 — Mutations + embedded page** | Enable mutation tools (create/update/move/subtasks/freeze/`run_schedule`; `delete_task` still excluded); `g.actor='agent'` audit attribution; deploy `hermes-webui` + subdomain + frame-ancestors proxy config; `#hermes` destination (tab, iframe, shortcut `6`, help-modal row, `HERMES_WEBUI_URL` env, hidden-when-unset). | Chat with Hermes **inside the app**; it creates/moves tasks that appear on the board on next refresh. | A task created in chat shows `actor='agent'` in `/api/logs`; destination passes the shell conventions (deep link, memory, shortcut). |
| **3 — Automations + mail** | Mail read tools + `email_to_task_draft` (with §8 injection guardrails); morning-brief and inbox-sweep cron jobs; stale-task nudge. | The daily routine runs unattended for a week. | User keeps at least two automations enabled voluntarily. |
| **4 — Deepening (optional)** | Flask→Hermes proxy blueprint + native pane experiments (Variant 2); "ask Hermes" per-task affordances; the §6 `AI_API_BASE_URL`→Hermes experiment, documented; preference-learning exploration over ChangeLog (`user`-corrects-`agent` signal); `delete_task` unlocked behind Hermes approvals. | Findings appended to this PRD; go/no-go on native pane. | — |

Testing strategy: MCP tools get their own pytest suite hitting a Flask test app via the token path (the sidecar's HTTP client pointed at `app.test_client()` through a thin adapter, or a live test server fixture); tool JSON schemas snapshot-tested so agent-facing contracts don't drift silently. The existing 122-test suite continues to guard route semantics that the tools inherit.

---

## 8. Security analysis

- **Trust domain**: single-user app; the bearer token grants what the cookie grants. Keep `simpler-mcp` unpublished on the docker network when Hermes is co-hosted; if remote, expose only via TLS reverse proxy, and rotate `API_TOKEN` like a password. `.env.example` gains `API_TOKEN=` with a "generate with `openssl rand -hex 32`" comment.
- **Hermes API server**: bind stays `127.0.0.1` (default); the Flask proxy (Variant 2) or the local webui are the only callers; never set broad `API_SERVER_CORS_ORIGINS`. Remember the Hermes docs' own warning: that API "exposes terminal access and file operations" — its key is as sensitive as SSH.
- **Prompt injection** (the real new risk): `read_mail` feeds *attacker-authored* content (any inbound email) into an agent holding mutation tools. Mitigations, layered: (1) tool descriptions instruct treating mail bodies as untrusted data (helps, insufficient alone); (2) v1 `include` list keeps `delete_task` and space/mailbox admin off entirely; (3) `email_to_task_draft` keeps the confirm-before-create conversational contract; (4) Hermes approvals gate anything sensitive; (5) `actor='agent'` audit + ChangeLog full snapshots make every agent action reviewable and reversible by hand. Phase 3 does not proceed until 1–5 are in place.
- **Iframe embedding**: `frame-ancestors` pinned to exactly the app origin (never `*`, never dropped without replacement); webui auth stays enabled even when framed; clipboard permission only if actually needed.
- **Secrets inventory after integration**: `APP_PASSWORD`, `SECRET_KEY` (+Fernet), `AI_API_KEY`, **`API_TOKEN`** (new, Simpler↔MCP↔Hermes), **`API_SERVER_KEY`** (Hermes, only if Variant 2/Jobs API used), webui password/OIDC. Document all in `doc/README.md` deployment notes.

## 9. Open questions (to resolve during the phases)

1. Where does Hermes run — same box as Simpler (docker network, simplest) or elsewhere (needs the TLS/proxy path for MCP)? *Assumed same box throughout.*
2. `hermes-webui` iframe auth cookie behavior (`SameSite` under third-party framing) — Phase 2 spike; upstream PR if it needs a flag (the project is small, vanilla, and patch-friendly).
3. Does the board need live refresh when Hermes mutates tasks in the background? v1: no (next poll/switch redraws). If it grates: cheap `updated_since` polling on the changelog while the app is visible — do NOT reach for websockets first.
4. Multi-space privacy: should some spaces be hidden from the agent (e.g. personal)? Possible cheaply: `agent_visible` flag on Space filtered in the token-auth path. Park until the user actually wants it.
5. Hermes profile strategy: dedicated `hermes profile create simpler` (isolated memory/model per §API-server multi-user pattern) vs the default profile carrying all platforms. Default profile assumed (one agent, full context is the point).

## 10. Sources

- Hermes Agent repo: https://github.com/NousResearch/hermes-agent · README (install, gateway, features)
- Docs (source: `website/docs/` in-repo; published at https://hermes-agent.nousresearch.com/docs/): MCP guide `guides/use-mcp-with-hermes.md`, MCP config reference `reference/mcp-config-reference.md`, API server `user-guide/features/api-server.md`, web dashboard `user-guide/features/web-dashboard.md`
- Relay connector contract (ruled out): `docs/relay-connector-contract.md` in the Hermes repo
- hermes-webui (community chat UI, embed target): https://github.com/nesquena/hermes-webui
- Open WebUI ↔ Hermes connection guide (validates the OpenAI-compatible path): https://docs.openwebui.com/getting-started/quick-start/connect-an-agent/hermes-agent/
- Hermes dashboard Profile Builder announcement (MCP-in-dashboard): https://www.marktechpost.com/2026/06/11/nous-research-ships-hermes-agent-profile-builder-identity-model-skills-and-mcp-servers-in-one-dashboard-flow/
- MCP Python SDK (FastMCP, streamable HTTP): https://github.com/modelcontextprotocol/python-sdk
- Simpler internals: `.opencode/context/CONTEXT.md`, `.opencode/context/topics/ai-parsing.md`, `doc/PROJECT_DESCRIPTION.md`
