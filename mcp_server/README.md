# simpler-mcp — the Simpler MCP server

An MCP (Model Context Protocol) sidecar that exposes Simpler's domain —
tasks, subtasks, spaces, notes, schedule, read-only mail, changelog — as
typed tools for any MCP client, primarily [Hermes
Agent](https://github.com/NousResearch/hermes-agent). It wraps the existing
REST API over HTTP (never the database), so every route invariant
(status⇔completed sync, subtask two-way sync, audited writes) is inherited,
and agent mutations show up in the ChangeLog with `actor='agent'`.

## Running

It ships as a compose service (see the root `docker-compose.yml`):

```bash
# in the repo root: set API_TOKEN in .env first (openssl rand -hex 32)
docker compose up -d          # web (:53000) + mcp (:8765, loopback only)
```

Standalone (e.g. for development):

```bash
pip install -r mcp_server/requirements.txt
SIMPLER_BASE_URL=http://localhost:53000 SIMPLER_API_TOKEN=<token> \
    python -m mcp_server.server
```

| Env var | Default | Meaning |
|---|---|---|
| `SIMPLER_BASE_URL` | `http://web:53000` | Simpler app base URL |
| `SIMPLER_API_TOKEN` | — | must equal the app's `API_TOKEN` |
| `MCP_BIND` | `0.0.0.0:8765` | listen address (streamable HTTP at `/mcp`) |

The compose file publishes the port on `127.0.0.1:8765` only — enough for a
Hermes installed on the same host. If Hermes runs elsewhere, front the port
with a TLS reverse proxy instead of exposing it directly.

## Registering in Hermes

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  simpler:
    url: "http://127.0.0.1:8765/mcp"
    timeout: 60
    tools:
      resources: false
      prompts: false
      # Recommended rollout: start read-only, then widen (PRD 002 §7).
      # include: [get_workspace_summary, list_tasks, get_task, list_spaces,
      #           get_calendar, list_notes, get_note, list_changelog]
```

Verify with `hermes mcp test simpler` (tools appear as
`mcp_simpler_<tool>`), then `/reload-mcp` in a running session.

## Tool surface (v1)

Read: `get_workspace_summary`, `list_tasks`, `get_task`, `list_spaces`,
`get_calendar`, `list_notes`, `get_note`, `list_changelog`,
`list_mailboxes`, `list_mail`, `read_mail`.

Mutate: `create_task`, `update_task`, `move_task`, `delete_task`,
`add_subtask`, `set_subtask`, `delete_subtask`, `toggle_freeze`,
`freeze_day`, `run_schedule`, `update_space_context`, `create_note`,
`append_to_note`, `email_to_task_draft`, `draft_tasks_from_text`.

Security notes (PRD 002 §8): keep `delete_task` and the mail tools out of
the Hermes `include` list until trust is established; mail bodies are
attacker-authored input to an agent holding mutation tools — the tool
descriptions carry the injection warnings, and every agent action is
reviewable via `list_changelog` (`actor='agent'`).
