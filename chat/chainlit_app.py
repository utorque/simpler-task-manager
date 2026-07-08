"""Chainlit entrypoint for the Simpler Assistant.

Loaded by `asgi.py` via `mount_chainlit(..., target=this file, path='/assistant')`
for the integrated app, or standalone for development:

    CHAINLIT_APP_ROOT=chat chainlit run chat/chainlit_app.py

Responsibilities here are wiring only — auth bridging, history persistence,
model picking, and streaming the provider reply. The reusable logic lives in
the sibling modules (`auth_bridge`, `data_layer`, `providers`), which stay
importable and testable without Chainlit's runtime.
"""

import os
import sys

# Chainlit loads this file by path; make the repo root importable so the
# `chat` package resolves regardless of who loaded us (asgi.py, chainlit CLI).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from chat import settings  # noqa: E402

settings.ensure_chainlit_env()  # before anything imports chainlit

import chainlit as cl  # noqa: E402

from chat.auth_bridge import is_authenticated  # noqa: E402
from chat.data_layer import build_data_layer  # noqa: E402
from chat.providers import LLMClient  # noqa: E402

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


# ===== Conversation ===========================================================

@cl.on_chat_start
async def on_chat_start():
    if not settings.ai_api_key():
        await cl.Message(
            content='⚠️ No AI provider configured — set `AI_API_KEY` (and '
                    '`AI_API_BASE_URL` / `CHAT_MODELS`) in `.env`.',
        ).send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    # Chainlit restores the message history into the chat context itself;
    # nothing to rebuild here.
    pass


@cl.on_message
async def on_message(message: cl.Message):
    history = cl.chat_context.to_openai()
    reply = cl.Message(content='')

    async def on_text(delta: str):
        await reply.stream_token(delta)

    try:
        await get_llm().stream_chat(
            model=current_model(),
            system=SYSTEM_PROMPT,
            messages=history,
            on_text=on_text,
        )
    except Exception as e:  # surface provider errors in-chat, don't crash the session
        await cl.Message(content=f'❌ Provider error: {e}').send()
        return
    await reply.update()
