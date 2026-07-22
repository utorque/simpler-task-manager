# The embedded Assistant (Chainlit)

The Assistant tab (press `6`) is a first-party [Chainlit](https://chainlit.io)
chat app living in this repo (`chat/`). It runs **inside the web container** —
`asgi.py` mounts it same-origin at `/assistant` next to the Flask app — so
there is no extra UI container, no reverse-proxy changes, and one login: the
chat authenticates by validating Simpler's own session cookie.

```
browser ──▶ web (uvicorn asgi:app :53000)
              ├── /            Flask app (unchanged)
              └── /assistant   Chainlit assistant ──▶ mcp     (:8765, workspace tools, audited)
                                                 ──▶ sandbox (:8766, code exec, shared /workspace)
```

## What it can do

- **Chat with history** — threads persist in `instance/chainlit.db`; pick the
  model per conversation (`CHAT_MODELS`).
- **Slash commands** — `/task`, `/note`, `/tasks`, `/notes`, `/skill` inject
  workspace entities into the conversation (a task always brings its linked
  note along). Starters are generated from the tasks currently in *Doing*.
- **Space filter** — the chips above the chat scope `/tasks`, `/notes` and the
  per-space AI guidance injected into the system prompt.
- **Agentic tools** — Simpler's MCP sidecar is pre-integrated (read AND write:
  create/update tasks, notes, run the scheduler… all audited as
  `actor='agent'`), plus `web_search` / `fetch_url`, skills
  (`chat/skills/*/SKILL.md`), and the execution sandbox. Extra MCP servers can
  be plugged in from the chat UI (🔌) or via `CHAT_MCP_SERVERS`.
- **Files** — attach files to a message (text is inlined, everything is stored
  in the shared workspace); any file the agent produces in the workspace is
  sent back as a download at the end of the turn.

## Setup (docker compose)

1. `cp .env.example .env`, then set at least:
   - `SECRET_KEY`, `APP_PASSWORD` — as before
   - `AI_API_KEY`, `AI_API_BASE_URL`, `AI_MODEL` — the assistant reuses the
     app's provider config (OpenAI-compatible or Anthropic)
   - `API_TOKEN` (`openssl rand -hex 32`) — gives the assistant (and the MCP
     sidecar) workspace access; unset = chat works but can't see tasks
   - optional: `CHAT_MODELS=modelA,modelB` for the model picker
2. `docker compose up -d --build`
3. Log in → **Assistant** tab (press `6`). Try: *“What's on my plate?”*, click
   a starter, or `/task` and pick something.

The compose file wires everything else: `SIMPLER_MCP_URL=http://mcp:8765/mcp`,
`SANDBOX_MCP_URL=http://sandbox:8766/mcp`, and the shared `/workspace` volume.

## The sandbox

`sandbox/` is a separate container exposing `run_python`, `run_shell` and file
tools over MCP. Isolation model:

- **Only** shared surface: the `/workspace` volume (uploads in, results out).
  No app database, no `.env`, no secrets.
- Non-root user, memory/pids/cpu limits, path escapes rejected.
- **No internet** by default — it sits on an `internal: true` compose network
  that only `web` can reach. If snippets legitimately need the network, add
  `default` to the sandbox service's `networks:`.
- Preinstalled for snippets: pandas, numpy, matplotlib, openpyxl, pillow,
  pypdf, requests (`sandbox/requirements.txt` — trim/extend freely).

## Running without compose (dev)

- `python src/app.py` — Flask only, Assistant tab hidden, app unchanged.
- `uvicorn asgi:app --port 53000` — full app incl. assistant. For workspace
  tools, also run the sidecars (or set `CHAT_LOCAL_SANDBOX=1` for in-process,
  unisolated sandbox tools):

  ```bash
  SIMPLER_BASE_URL=http://127.0.0.1:53000 SIMPLER_API_TOKEN=$API_TOKEN \
      MCP_BIND=127.0.0.1:8765 python mcp_server/server.py &
  SANDBOX_WORKSPACE=/tmp/simpler-ws MCP_BIND=127.0.0.1:8766 python sandbox/server.py &
  SIMPLER_MCP_URL=http://127.0.0.1:8765/mcp SANDBOX_MCP_URL=http://127.0.0.1:8766/mcp \
      CHAT_FILES_DIR=/tmp/simpler-ws uvicorn asgi:app --port 53000
  ```

## End-to-end verification

`scripts/e2e/` contains a self-contained harness that boots the whole
topology as local processes with a **mock** OpenAI-compatible model and
drives a real browser-equivalent session over socket.io (auth bridge,
streaming, MCP task creation with audit, sandbox file round-trip, history):

```bash
pip install -r requirements.txt "python-socketio[client]" websocket-client
bash scripts/e2e/run_stack.sh     # WARNING: wipes instance/*.db
python scripts/e2e/drive.py       # 13 checks, exits non-zero on failure
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| No Assistant tab | You're running `python src/app.py` (Flask only) — use `uvicorn asgi:app` / the docker image. |
| Chat asks for a login | The header-auth bridge rejected the session cookie: `SECRET_KEY` differs between processes, or you're not logged into Simpler in this browser. |
| Replies error with provider messages | `AI_API_KEY` / `AI_API_BASE_URL` / model name — the error text is shown in-chat. |
| Assistant can't see tasks | `API_TOKEN` unset, or the `mcp` sidecar is down / `SIMPLER_MCP_URL` wrong. |
| Sandbox tools missing | `SANDBOX_MCP_URL` unset (or sandbox container down). Dev fallback: `CHAT_LOCAL_SANDBOX=1`. |
| Produced files not returned | They must be written into the shared workspace (`/workspace` in compose, `CHAT_FILES_DIR` otherwise). |
