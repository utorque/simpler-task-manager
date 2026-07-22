"""Chainlit entrypoint for the Simpler Assistant.

Loaded by `asgi.py` via `mount_chainlit(..., target=this file, path='/assistant')`
for the integrated app, or standalone for development:

    CHAINLIT_APP_ROOT=chat chainlit run chat/chainlit_app.py

Responsibilities here are wiring only — auth bridging, history persistence,
model picking, slash commands, starters, the space-filter bridge, and
streaming the provider reply. The reusable logic lives in the sibling
modules (`auth_bridge`, `data_layer`, `providers`, `simpler_client`,
`workspace`, `commands`), which stay importable and testable without
Chainlit's runtime.
"""

import json
import os
import sys
from datetime import datetime

# Chainlit loads this file by path; make the repo root importable so the
# `chat` package resolves regardless of who loaded us (asgi.py, chainlit CLI).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from chat import settings  # noqa: E402

settings.ensure_chainlit_env()  # before anything imports chainlit

import chainlit as cl  # noqa: E402

from chat import assistant_settings, commands, files, modes, sandbox_tools, simpler_client, skills, web_tools, workspace  # noqa: E402
from chat.agent import AgentHooks, run_agent  # noqa: E402
from chat.auth_bridge import is_authenticated  # noqa: E402
from chat.data_layer import build_data_layer  # noqa: E402
from chat.mcp_tools import MCPToolServer, tool_to_spec  # noqa: E402
from chat.providers import LLMClient  # noqa: E402
from chat.simpler_client import SimplerAPIError  # noqa: E402
from chat.toolbox import Toolbox  # noqa: E402

# ===== Auth: one login for the whole app =====================================
# The assistant is same-origin with Simpler, so the Flask session cookie rides
# along on every request; a validly-signed, logged-in session IS the identity.
# Single-user app -> a single fixed Chainlit identifier ("owner") so all chat
# history belongs to the one real user.

@cl.header_auth_callback
async def auth_from_simpler_session(headers):
    if is_authenticated(headers.get('cookie'), settings.secret_key()):
        return cl.User(identifier='owner', metadata={'provider': 'simpler-session'})
    return None


# ===== Chat history ===========================================================

@cl.data_layer
def data_layer():
    return build_data_layer(settings.chainlit_db_path())


# ===== Model picker (Modes: chat-bar picker, switchable mid-conversation) =====
# Model list source: instance/assistant/models.json (settings panel writes
# it), falling back to the CHAT_MODELS/AI_MODEL env chain. Selection is read
# per message from msg.modes, so it persists within a chat and switches live.

def build_chat_modes() -> list[cl.Mode]:
    model_options = modes.build_model_mode_options(
        assistant_settings.available_models())
    reasoning_options = modes.build_reasoning_mode_options(
        assistant_settings.available_reasoning_levels())
    return [
        cl.Mode(id=modes.MODEL_MODE_ID, name='Model',
                options=[cl.ModeOption(**opt) for opt in model_options]),
        cl.Mode(id=modes.REASONING_MODE_ID, name='Reasoning',
                options=[cl.ModeOption(**opt) for opt in reasoning_options]),
        cl.Mode(id=modes.CONTEXT_MODE_ID, name='Context',
                options=[cl.ModeOption(**opt)
                         for opt in modes.build_context_mode_options()]),
    ]


async def publish_modes():
    await cl.context.emitter.set_modes(build_chat_modes())


def get_llm(reasoning_effort: str | None = None) -> LLMClient:
    return LLMClient(
        api_key=settings.ai_api_key(),
        base_url=settings.ai_base_url(),
        max_tokens=settings.max_tokens(),
        reasoning_effort=reasoning_effort,
    )


# ===== Tools: pre-integrated MCP servers + UI-added MCP + natives ============

_preintegrated_servers: list[MCPToolServer] | None = None


def preintegrated_servers() -> list[MCPToolServer]:
    """Simpler's own MCP sidecar (SIMPLER_MCP_URL) + CHAT_MCP_SERVERS,
    instantiated once per process (tool listings are cached inside)."""
    global _preintegrated_servers
    if _preintegrated_servers is None:
        servers = []
        if settings.simpler_mcp_url():
            servers.append(MCPToolServer('simpler', settings.simpler_mcp_url()))
        if settings.sandbox_mcp_url():
            servers.append(MCPToolServer('sandbox', settings.sandbox_mcp_url()))
        for name, url in settings.extra_mcp_servers().items():
            servers.append(MCPToolServer(name, url))
        _preintegrated_servers = servers
    return _preintegrated_servers


@cl.on_mcp_connect
async def on_mcp_connect(connection, session):
    """User plugged an MCP server in through the UI: list its tools once and
    keep the (Chainlit-managed) session for tool calls."""
    listing = await session.list_tools()
    specs = [tool_to_spec(t, connection.name) for t in listing.tools]
    sessions = cl.user_session.get('mcp_sessions') or {}
    sessions[connection.name] = {'session': session, 'specs': specs}
    cl.user_session.set('mcp_sessions', sessions)
    await cl.Message(
        content=f'🔌 MCP server **{connection.name}** connected '
                f'({len(specs)} tools).').send()


@cl.on_mcp_disconnect
async def on_mcp_disconnect(name: str, session):
    sessions = cl.user_session.get('mcp_sessions') or {}
    sessions.pop(name, None)
    cl.user_session.set('mcp_sessions', sessions)


def add_native_tools(toolbox: Toolbox):
    if settings.web_tools_enabled():
        web_tools.register(toolbox)
    skills.register(toolbox)
    files.register(toolbox, settings.files_dir())
    if not settings.sandbox_mcp_url() and settings.local_sandbox_enabled():
        sandbox_tools.register(toolbox, settings.files_dir())


SIMPLER_SERVER_NAME = 'simpler'


async def build_toolbox(simpler: bool = True) -> Toolbox:
    """The tool table for one turn. `simpler=False` (Context picker on
    *Generic*) leaves the Simpler sidecar out — that is the ~26-spec bulk of
    the tool payload. Everything else (sandbox, extra MCP servers, UI-added
    sessions, natives) is domain-agnostic and stays in both modes."""
    toolbox = Toolbox()
    for server in preintegrated_servers():
        if not simpler and server.name == SIMPLER_SERVER_NAME:
            continue
        try:
            await toolbox.add_mcp_server(server)
        except Exception as e:
            # A down sidecar must not take the chat down with it.
            print(f'[assistant] MCP server {server.name!r} unavailable: {e}')
    try:
        mcp_sessions = cl.user_session.get('mcp_sessions') or {}
    except Exception:
        # No Chainlit session context (settings-panel composition viewer):
        # only pre-integrated servers + natives.
        mcp_sessions = {}
    for name, entry in mcp_sessions.items():
        toolbox.add_mcp_session(name, entry['session'], entry['specs'])
    add_native_tools(toolbox)
    return toolbox


# ===== Space filter (shell subheader -> chat/public/simpler-bridge.js) =======

@cl.on_window_message
async def on_window_message(message):
    """The shell's space chips land here as JSON strings (see
    chat/public/simpler-bridge.js). Store the filter on the session; it
    scopes /tasks & /notes and the space guidance in the system prompt."""
    try:
        data = json.loads(message) if isinstance(message, str) else message
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(data, dict):
        return
    if data.get('type') == 'simpler-space-filter':
        ids = data.get('space_ids')
        if isinstance(ids, list):
            ids = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
            cl.user_session.set('space_filter', ids or None)
        else:
            cl.user_session.set('space_filter', None)
    elif data.get('type') == 'simpler-starter-click':
        await on_starter_click(data.get('label') or '')
    elif data.get('type') == 'simpler-pin-task':
        await on_pin_task(data.get('task_id'))


def selected_space_ids() -> list[int] | None:
    try:
        return cl.user_session.get('space_filter')
    except Exception:
        # No Chainlit session context (settings-panel composition viewer,
        # tests): no filter.
        return None


# ===== Starters (tasks in Doing) + composer commands ==========================

async def build_starter_specs() -> list[dict]:
    doing = []
    if simpler_client.configured():
        try:
            doing = await simpler_client.list_tasks(status='doing')
        except SimplerAPIError:
            doing = []
    return commands.build_starters(doing)


@cl.set_starters
async def starters():
    # message = the prefill seed: the bridge intercepts the click so it is
    # never auto-sent — it only reaches the model if the bridge is absent
    # (graceful degradation to the old fire-and-send behavior).
    return [cl.Starter(label=spec['label'], message=spec['prefill'],
                       command=spec.get('command'))
            for spec in await build_starter_specs()]


async def inject_and_prefill(command: str | None, prefill: str):
    """Run a command's context injection into the thread (when there is one),
    then hand the editable seed to the bridge, which writes it into the
    composer — nothing is sent to the model until the user hits enter."""
    if command:
        block, error = await commands.handle_command(
            command, prefill, selected_space_ids())
        if error:
            await cl.Message(content=error).send()
        elif block:
            await cl.Message(content=block, type='system_message',
                             author='Workspace context').send()
    await cl.send_window_message(
        {'type': 'simpler-starter-prefill', 'prefill': prefill})


async def on_starter_click(label: str):
    """Bridge-intercepted starter click: run the starter's command injection
    (task starters land their /task context block in the thread), then hand
    the editable seed back to the bridge to prefill the composer."""
    spec = commands.starter_by_label(label, await build_starter_specs())
    if spec is None:
        return
    await inject_and_prefill(spec.get('command'), spec['prefill'])


async def on_pin_task(task_id):
    """The shell's board card robot button (src/static/js/app.js → localStorage
    → chat/public/simpler-bridge.js): pin one task to the conversation, exactly
    like clicking its starter — /task block in the thread, composer seeded with
    the task ref — except it works on a running conversation too."""
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return
    await inject_and_prefill('task', f"#{task_id} — ")


async def register_commands(simpler: bool = True):
    """Publish the composer's slash commands. In Generic mode only the
    domain-agnostic ones survive (`/skill`) — the workspace injectors would
    have nothing to talk to. Re-published per message, so flipping the
    Context picker updates the composer from the next turn on."""
    if not simpler_client.configured():
        return
    await cl.context.emitter.set_commands(
        commands.COMMANDS if simpler else commands.GENERIC_COMMANDS)


# ===== Conversation ===========================================================

@cl.on_chat_start
async def on_chat_start():
    await register_commands()
    await publish_modes()
    if not settings.ai_api_key():
        await cl.Message(
            content='⚠️ No AI provider configured — set `AI_API_KEY` (and '
                    '`AI_API_BASE_URL` / `CHAT_MODELS`) in `.env`.',
        ).send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    # Chainlit restores the message history into the chat context itself.
    # Pre-Modes threads keep their history; their old profile selection is
    # simply gone (no backfill) — the pickers start at the defaults.
    await register_commands()
    await publish_modes()


async def build_system_prompt_layers(toolbox=None, spaces=None,
                                     simpler: bool = True) -> list[dict]:
    """The system prompt as an ordered list of named layers — the single
    source both `build_system_prompt` (joined text for the model) and the
    settings panel's composition viewer (structured metadata) derive from.

    The base prompt is re-read every call (instance override when the user
    edited it in-app, else the shipped default) so edits are live — the
    dynamic layers below were always per-turn. Pass pre-fetched `spaces` to
    skip the API round-trip (the Flask composition route reads them straight
    from the DB — it cannot loop back into its own HTTP server).

    `simpler=False` (Context picker on *Generic*) resolves the base prompt to
    its workspace-free flavour and drops the spaces layer entirely, spaces
    API call included."""
    base_path = assistant_settings.system_prompt_path()
    is_override = (base_path == assistant_settings.system_prompt_override_path())
    try:
        last_modified = datetime.fromtimestamp(
            os.path.getmtime(base_path)).isoformat(timespec='seconds')
    except OSError:
        last_modified = None
    layers = [{
        'kind': 'base',
        'name': os.path.basename(base_path)
                + (' (instance override)' if is_override else ' (shipped default)'),
        'source': 'instance' if is_override else 'bundled',
        'last_modified': last_modified,
        'text': assistant_settings.load_system_prompt(simpler=simpler),
    }]

    now = datetime.now()
    layers.append({
        'kind': 'datetime',
        'text': f"Current date and time: {now.strftime('%Y-%m-%d %H:%M')} "
                f"({now.strftime('%A')}).",
    })

    if simpler:
        selected = selected_space_ids()
        if spaces is None and simpler_client.configured():
            try:
                spaces = await simpler_client.list_spaces()
            except SimplerAPIError as e:
                layers.append({'kind': 'spaces_guidance', 'sources': [],
                               'text': f'(Workspace API unavailable right now: {e})'})
        if spaces is not None:
            shown = [s['name'] for s in spaces
                     if selected is None or s['id'] in selected] \
                    or [s['name'] for s in spaces]
            layers.append({'kind': 'spaces_guidance', 'sources': shown,
                           'text': workspace.format_spaces_guidance(spaces, selected)})
        elif not simpler_client.configured():
            # State the ONE real remedy. Told only that the token is unset, models
            # invent plausible-but-nonexistent fix paths ("Settings → API Token",
            # "connect the desktop app") and send the user hunting through a UI
            # that has no such screen.
            layers.append({'kind': 'spaces_guidance', 'sources': [],
                           'text': '(Workspace access is not configured: API_TOKEN '
                                   'unset — you cannot see or change tasks, notes '
                                   'or spaces, and every workspace tool will fail. '
                                   'The ONLY fix is server-side: set API_TOKEN in '
                                   'the .env file next to docker-compose.yml '
                                   '(generate one with `openssl rand -hex 32`) and '
                                   'restart with `docker compose up -d`. There is '
                                   'no in-app settings screen for this — do not '
                                   'invent one, and do not ask which client the '
                                   'user is on.)'})

    tool_names = [spec['name'] for spec in toolbox.specs()] if toolbox else []
    if tool_names:
        layers.append({
            'kind': 'tools',
            'items': tool_names,
            'text': '## Tools\n'
                    f"You can call these tools: {', '.join(tool_names)}. "
                    'Workspace mutations are audited. Confirm with the user '
                    'before anything destructive (deletes) — creating/updating '
                    'tasks or notes they asked for needs no extra confirmation.',
        })

    skills_section = skills.prompt_section()
    if skills_section:
        layers.append({
            'kind': 'skills',
            'items': [s['name'] for s in skills.list_skills()],
            'text': skills_section,
        })
    return layers


async def build_system_prompt(toolbox=None, simpler: bool = True) -> str:
    layers = await build_system_prompt_layers(toolbox, simpler=simpler)
    return '\n\n'.join(layer['text'] for layer in layers if layer.get('text'))


class UIHooks(AgentHooks):
    """Render agent events: one streamed message per model round, one
    collapsible step per tool call."""

    def __init__(self):
        self._message: cl.Message | None = None
        self._steps: dict[str, cl.Step] = {}

    async def on_text(self, delta: str):
        if self._message is None:
            self._message = cl.Message(content='')
        await self._message.stream_token(delta)

    async def on_round_end(self, result):
        if self._message is not None:
            await self._message.update()
            self._message = None

    async def on_tool_start(self, call):
        step = cl.Step(name=call.name, type='tool')
        step.input = json.dumps(call.arguments, indent=2, ensure_ascii=False)
        await step.send()
        self._steps[call.id] = step

    async def on_tool_end(self, call, output: str):
        step = self._steps.pop(call.id, None)
        if step is not None:
            step.output = output
            await step.update()


@cl.on_message
async def on_message(message: cl.Message):
    # Chat-bar Context picker: 'Generic' unplugs the whole Simpler layer for
    # this turn (sidecar tools, spaces, workspace prompt sections, workspace
    # commands) so a general question doesn't pay for any of it.
    message_modes = getattr(message, 'modes', None)
    simpler = modes.simpler_context_enabled(message_modes)
    await register_commands(simpler)

    if not simpler and message.command in commands.WORKSPACE_COMMAND_IDS:
        await cl.Message(
            content='⚠️ `/' + message.command + '` needs the workspace — switch '
                    'the **Context** picker back to *Simpler*.').send()
        return

    # Attached files land in the thread as a persisted context block (text
    # inlined, everything stored in the assistant's file workspace).
    file_block = files.ingest_elements(message.elements, settings.files_dir())
    if file_block:
        await cl.Message(content=file_block, type='system_message',
                         author='Attached files').send()

    # Slash commands inject workspace context as a persisted system message
    # BEFORE the model answers, so it is part of the thread from here on.
    if message.command:
        block, error = await commands.handle_command(
            message.command, message.content, selected_space_ids())
        if error:
            await cl.Message(content=error).send()
            return
        if block:
            await cl.Message(content=block, type='system_message',
                             author='Workspace context').send()

    history = cl.chat_context.to_openai()
    # The model delivers files by link (get_file_link) embedded in its reply —
    # no post-turn attachment flush, and scratch files are never auto-surfaced.
    toolbox = await build_toolbox(simpler=simpler)

    model = modes.current_model_from_modes(
        message_modes, default=assistant_settings.available_models()[0])
    reasoning = modes.current_reasoning_from_modes(message_modes, 'medium')
    try:
        await run_agent(
            llm=get_llm(reasoning_effort=reasoning),
            model=model,
            system=await build_system_prompt(toolbox, simpler=simpler),
            history=history,
            toolbox=toolbox,
            hooks=UIHooks(),
            max_rounds=settings.agent_max_rounds(),
        )
    except Exception as e:  # surface provider errors in-chat, don't crash the session
        await cl.Message(content=f'❌ Provider error: {e}').send()
        return
