# Setting up the Hermes agent integration

Everything runs from the one `docker-compose.yml` in this repo — Simpler, the
MCP sidecar, **and Hermes itself** (agent + chat UI in the `hermes-webui`
container). No host install of Hermes, **no nginx/DNS changes**: the chat UI
is reverse-proxied by the app itself at `/hermes-ui/` (same origin, behind
your normal Simpler login) and embedded as the **Hermes tab (press `6`)**.

```
browser ──▶ your nginx ──▶ web (Flask :53000)
                             ├── /            the app
                             ├── /hermes-ui/  authenticated proxy ──▶ hermes-webui (:8787, container-only)
                             └── /api/*       REST ◀── mcp sidecar (:8765, container-only) ◀── the agent's tools
```

Design/background: `.opencode/plans/002_PRD_hermes-agent-integration.md`.

---

## 0. Prerequisites

- Docker ≥ 20.10 with Compose v2 (`docker compose version`) — the
  `hermes-webui` service builds straight from a git URL, which needs BuildKit
  (default in current Docker).
- An LLM API key **for the agent** (separate from Simpler's `AI_API_KEY`):
  OpenRouter, Anthropic, OpenAI, Nous Portal… anything Hermes supports.
- Outbound internet on first start (the container auto-installs Hermes Agent
  once, into a persisted volume).

## 1. Configure Simpler (`.env`)

```bash
cp .env.example .env   # if you haven't already
openssl rand -hex 32   # → paste as API_TOKEN in .env
```

`API_TOKEN` is the bearer credential the MCP sidecar uses against the REST
API (agent mutations are audited as `actor='agent'`). The compose file
already sets `HERMES_WEBUI_INTERNAL_URL=http://hermes-webui:8787` on the
`web` service — that alone makes the Hermes tab appear. To run *without* the
integration, comment that line out and skip the `hermes-webui` service
(`docker compose up -d web mcp`).

## 2. Configure the agent (`./hermes-home/`)

The container bind-mounts `./hermes-home` as the agent's `~/.hermes`
(gitignored — it will hold API keys, memory, sessions). Seed it:

```bash
mkdir -p hermes-home hermes-workspace
```

**`hermes-home/.env`** — the agent's own secrets (pick your provider; see
[Hermes provider docs](https://hermes-agent.nousresearch.com/docs/integrations/providers)):

```bash
OPENROUTER_API_KEY=sk-or-...        # or ANTHROPIC_API_KEY / OPENAI_API_KEY / ...
```

**`hermes-home/config.yaml`** — model + the Simpler MCP server:

```yaml
# model/provider — adjust to your key above (or configure later in the
# webui's Settings panel instead)
model: "anthropic/claude-sonnet-5"   # example for OpenRouter

mcp_servers:
  simpler:
    url: "http://mcp:8765/mcp"       # compose-internal; never exposed to the host
    timeout: 60
    tools:
      resources: false
      prompts: false
      # optional: start read-only by allowlisting, then widen as trust grows —
      # include: [get_workspace_summary, list_tasks, get_task, list_spaces,
      #           get_calendar, list_notes, get_note, list_changelog]
```

Notes:
- The MCP endpoint carries no auth of its own — it is reachable **only** on
  the compose network (no `ports:` published). Don't publish `8765` unless
  you front it with TLS + auth.
- Config-file details vary slightly across Hermes versions; anything here
  can also be set from the webui's Settings/MCP panels once it's up.

## 3. Start everything

```bash
docker compose up -d --build
docker compose logs -f hermes-webui   # first start: installs Hermes Agent (a few minutes)
```

Subsequent starts are fast — the agent lives in `./hermes-home` now.

## 4. Use it

1. Open Simpler as usual (your existing nginx URL — nothing changed there).
2. Log in → a **Hermes** tab is in the header → click it or press `6`.
3. First visit loads the hermes-webui chat. Pick/confirm the model if asked.
4. Say: *“Call get_workspace_summary and tell me what's on my plate.”*
5. Then: *“Create a task ‘test from Hermes’ in the work space, priority 3.”*
   → switch to Tasks (`1`): the card is on the board.

## 5. Verify each layer (troubleshooting order)

```bash
# a) bearer auth works (expect JSON task list, not 401):
curl -s -H "Authorization: Bearer $API_TOKEN" http://localhost:53000/api/tasks | head -c 300

# b) MCP server answers (from inside the compose network):
docker compose exec web python -c "
import requests
r = requests.post('http://mcp:8765/mcp',
    json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'t','version':'0'}}},
    headers={'Accept':'application/json, text/event-stream'})
print(r.status_code, 'serverInfo' in r.text)"        # → 200 True

# c) webui is up behind the proxy (expect 401 before login — that's the gate working):
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:53000/hermes-ui/

# d) agent actions are audited:
curl -s -H "Authorization: Bearer $API_TOKEN" 'http://localhost:53000/api/logs?limit=5'
#    → entries with "actor": "agent" after chat-driven mutations
```

| Symptom | Likely cause / fix |
|---|---|
| No Hermes tab | `HERMES_WEBUI_INTERNAL_URL` not reaching the app — it's set in `docker-compose.yml` on `web`; rebuild/recreate (`docker compose up -d --force-recreate web`). |
| Tab shows an error / blank | `docker compose logs hermes-webui` — usually still installing on first boot, or the agent install failed (network). The proxy answers 502 while the container is down. |
| Chat replies with provider/auth errors | Key missing/wrong in `hermes-home/.env`, or model name not valid for that provider — fix and `docker compose restart hermes-webui`. |
| Agent doesn't see Simpler tools | `mcp_servers` block malformed in `hermes-home/config.yaml`, or `mcp` service down. Ask the agent to “list your MCP servers/tools”; restart `hermes-webui` after config edits. |
| Tools fail with `401` | `API_TOKEN` in `.env` empty or changed after `mcp` started — `docker compose up -d --force-recreate mcp`. |
| Permission errors in `hermes-home/` | Set `WANTED_UID`/`WANTED_GID` in `.env` to your host user (`id -u` / `id -g`); defaults are 1000. |
| Build of `hermes-webui` fails | Old Docker without git build contexts — upgrade, or clone the repo next to this one and point `build.context` at the local path. |
| Streaming stalls behind your nginx | Only if nginx buffers aggressively: `proxy_buffering off;` for your existing Simpler location helps SSE; usually unnecessary. |

## 6. Security notes

- **One gate**: the webui has no published port; the only way in is
  `/hermes-ui/`, which requires Simpler's login. For a second layer inside
  the frame, set `HERMES_WEBUI_PASSWORD` on the `hermes-webui` service.
- `./hermes-home` contains the agent's API keys, memory, and full chat
  history — it is gitignored; back it up like `instance/`.
- The agent can mutate tasks/notes through the MCP tools. `delete_task`
  exists but you can keep it (and anything else) out via the `tools.include`
  allowlist shown above. Mail tools are read-only by construction, and every
  agent write lands in the ChangeLog (`actor='agent'`) with full snapshots.
- Treat email content the agent reads as untrusted (prompt injection): the
  PRD §8 lists the layered guardrails; the conservative allowlist is the big
  one.

## 7. Optional next steps

- **Messaging + cron automations** (morning brief, inbox sweep — PRD §5):
  these need the Hermes *gateway* process, which this compose doesn't run.
  Options: run `docker compose exec -it hermes-webui bash` and use the
  installed agent's `hermes gateway setup` interactively, or see upstream's
  `docker-compose.two-container.yml` (separate agent container) at
  https://github.com/nesquena/hermes-webui for a dedicated gateway service.
- **Pin the webui build** for reproducibility: change the build context to
  `...hermes-webui.git#<tag-or-commit>` in `docker-compose.yml`.
- **Sibling-subdomain embed instead of the proxy** (e.g. if you want the
  webui reachable outside the app too): publish `8787`, serve it at
  `hermes.example.com` with `Content-Security-Policy: frame-ancestors
  <app origin>`, unset `HERMES_WEBUI_INTERNAL_URL` and set
  `HERMES_WEBUI_URL=https://hermes.example.com` — PRD §4.2 has the Caddy/nginx
  snippets. (This is the one path that *does* touch your reverse proxy.)
