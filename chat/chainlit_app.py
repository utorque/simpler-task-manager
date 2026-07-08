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

from chat import commands, files, simpler_client, workspace  # noqa: E402
from chat.agent import AgentHooks, run_agent  # noqa: E402
from chat.auth_bridge import is_authenticated  # noqa: E402
from chat.data_layer import build_data_layer  # noqa: E402
from chat.mcp_tools import MCPToolServer, tool_to_spec  # noqa: E402
from chat.providers import LLMClient  # noqa: E402
from chat.simpler_client import SimplerAPIError  # noqa: E402
from chat.toolbox import Toolbox  # noqa: E402

SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), 'prompts', 'system.md')


def load_system_prompt() -> str:
    try:
        with open(SYSTEM_PROMPT_PATH, encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return 'You are the built-in assistant of Simpler, a personal task/notes workspace.'


SYSTEM_PROMPT = load_system_prompt()


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


# ===== Model picker (chat profiles = models from .env) ========================

@cl.set_chat_profiles
async def chat_profiles():
    models = settings.chat_models()
    return [
        cl.ChatProfile(
            name=model,
            markdown_description=f'Answer with **{model}** via the configured provider.',
            default=(index == 0),
        )
        for index, model in enumerate(models)
    ]


def current_model() -> str:
    return cl.user_session.get('chat_profile') or settings.chat_models()[0]


def get_llm() -> LLMClient:
    return LLMClient(
        api_key=settings.ai_api_key(),
        base_url=settings.ai_base_url(),
        max_tokens=settings.max_tokens(),
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
    """In-process tools (extended by later steps: web search, sandbox
    fallback)."""


async def build_toolbox() -> Toolbox:
    toolbox = Toolbox()
    for server in preintegrated_servers():
        try:
            await toolbox.add_mcp_server(server)
        except Exception as e:
            # A down sidecar must not take the chat down with it.
            print(f'[assistant] MCP server {server.name!r} unavailable: {e}')
    for name, entry in (cl.user_session.get('mcp_sessions') or {}).items():
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
    if isinstance(data, dict) and data.get('type') == 'simpler-space-filter':
        ids = data.get('space_ids')
        if isinstance(ids, list):
            ids = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
            cl.user_session.set('space_filter', ids or None)
        else:
            cl.user_session.set('space_filter', None)


def selected_space_ids() -> list[int] | None:
    return cl.user_session.get('space_filter')


# ===== Starters (tasks in Doing) + composer commands ==========================

@cl.set_starters
async def starters():
    doing = []
    if simpler_client.configured():
        try:
            doing = await simpler_client.list_tasks(status='doing')
        except SimplerAPIError:
            doing = []
    return [cl.Starter(**spec) for spec in commands.build_starters(doing)]


async def register_commands():
    if simpler_client.configured():
        await cl.context.emitter.set_commands(commands.COMMANDS)


# ===== Conversation ===========================================================

@cl.on_chat_start
async def on_chat_start():
    await register_commands()
    if not settings.ai_api_key():
        await cl.Message(
            content='⚠️ No AI provider configured — set `AI_API_KEY` (and '
                    '`AI_API_BASE_URL` / `CHAT_MODELS`) in `.env`.',
        ).send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    # Chainlit restores the message history into the chat context itself.
    await register_commands()


async def build_system_prompt(toolbox=None) -> str:
    parts = [SYSTEM_PROMPT,
             f"Current date and time: {datetime.now().strftime('%Y-%m-%d %H:%M')} "
             f"({datetime.now().strftime('%A')})."]
    if simpler_client.configured():
        try:
            spaces = await simpler_client.list_spaces()
            parts.append(workspace.format_spaces_guidance(spaces, selected_space_ids()))
        except SimplerAPIError as e:
            parts.append(f'(Workspace API unavailable right now: {e})')
    else:
        parts.append('(Workspace access is not configured: API_TOKEN unset — '
                     'you cannot see tasks/notes/spaces.)')
    if toolbox is not None and toolbox.specs():
        names = ', '.join(spec['name'] for spec in toolbox.specs())
        parts.append(
            '## Tools\n'
            f'You can call these tools: {names}. Workspace mutations are '
            'audited. Confirm with the user before anything destructive '
            '(deletes) — creating/updating tasks or notes they asked for '
            'needs no extra confirmation.')
    return '\n\n'.join(parts)


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
    toolbox = await build_toolbox()

    try:
        await run_agent(
            llm=get_llm(),
            model=current_model(),
            system=await build_system_prompt(toolbox),
            history=history,
            toolbox=toolbox,
            hooks=UIHooks(),
            max_rounds=settings.agent_max_rounds(),
        )
    except Exception as e:  # surface provider errors in-chat, don't crash the session
        await cl.Message(content=f'❌ Provider error: {e}').send()
