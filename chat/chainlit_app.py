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

from chat import commands, simpler_client, workspace  # noqa: E402
from chat.auth_bridge import is_authenticated  # noqa: E402
from chat.data_layer import build_data_layer  # noqa: E402
from chat.providers import LLMClient  # noqa: E402
from chat.simpler_client import SimplerAPIError  # noqa: E402

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


async def build_system_prompt() -> str:
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
    return '\n\n'.join(parts)


@cl.on_message
async def on_message(message: cl.Message):
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
    reply = cl.Message(content='')

    async def on_text(delta: str):
        await reply.stream_token(delta)

    try:
        await get_llm().stream_chat(
            model=current_model(),
            system=await build_system_prompt(),
            messages=history,
            on_text=on_text,
        )
    except Exception as e:  # surface provider errors in-chat, don't crash the session
        await cl.Message(content=f'❌ Provider error: {e}').send()
        return
    await reply.update()
