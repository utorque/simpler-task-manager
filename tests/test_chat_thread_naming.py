"""Auto-naming: a new chat gets a 2-3 word title on its first message.

Chainlit names a thread after the first user message verbatim, which turns
the history sidebar into a column of half-paragraphs. chat/thread_naming.py
asks the model for a short title and cleans up whatever it answers;
chainlit_app wires it in — once per chat, after the turn (Chainlit's own
naming runs concurrently with on_message and would otherwise win), persisted
through the data layer.
"""

import asyncio
import sqlite3
import uuid

import pytest
from chainlit.user import User

from chat import chainlit_app, settings, thread_naming
from chat.data_layer import build_data_layer
from chat.providers import ChatResult


def run(coro):
    return asyncio.run(coro)


class StubLLM:
    """LLMClient-shaped: records the naming call, returns a canned answer."""

    def __init__(self, text='', error=None):
        self.text = text
        self.error = error
        self.calls = []

    async def stream_chat(self, model, system, messages, tools=None, on_text=None):
        self.calls.append({'model': model, 'system': system, 'messages': messages,
                           'tools': tools})
        if self.error:
            raise self.error
        return ChatResult(text=self.text)


# ===== Cleaning the model's answer ============================================

@pytest.mark.parametrize('raw, expected', [
    ('Grocery shopping list', 'Grocery shopping list'),
    ('"Quarterly budget review"', 'Quarterly budget review'),
    ('**Trip planning**', 'Trip planning'),
    ('Title: Kanban cleanup', 'Kanban cleanup'),
    ('kanban cleanup', 'Kanban cleanup'),               # capitalized
    ('Deploy pipeline fix.', 'Deploy pipeline fix'),
    ('Sure! Here it is:\nTax filing help', 'Sure Here it'),  # first line wins
    ('Réunion de lundi', 'Réunion de lundi'),           # keeps the language
    ('MCP server debugging session today', 'MCP server debugging'),  # <= 3 words
])
def test_clean_title(raw, expected):
    assert thread_naming.clean_title(raw) == expected


def test_clean_title_is_short_and_bounded():
    title = thread_naming.clean_title(
        'Extraordinarily complicated internationalization refactoring')
    # Three words would blow the char budget, so the title stops at two.
    assert title == 'Extraordinarily complicated'
    assert len(title) <= thread_naming.MAX_CHARS

    long_words = thread_naming.clean_title('antidisestablishmentarianism ' * 3)
    assert len(long_words) <= thread_naming.MAX_CHARS


def test_clean_title_rejects_junk():
    assert thread_naming.clean_title('') == ''
    assert thread_naming.clean_title('   \n  ') == ''
    assert thread_naming.clean_title('...') == ''
    assert thread_naming.clean_title(None) == ''


# ===== Generating one ==========================================================

def test_generate_title_asks_the_model_and_cleans_the_answer():
    llm = StubLLM(text='"Sprint Planning"')
    title = run(thread_naming.generate_title(
        llm, 'title-model', 'Can you help me plan the next sprint for the team?'))

    assert title == 'Sprint Planning'
    call = llm.calls[0]
    assert call['model'] == 'title-model'
    assert call['tools'] is None  # naming never needs tools
    assert 'plan the next sprint' in call['messages'][0]['content']


def test_generate_title_falls_back_to_the_users_own_words():
    """No model, no answer, junk answer -> still a short title, never a crash."""
    seed = 'Refactor the calendar sync so recurring events stop duplicating'

    assert run(thread_naming.generate_title(
        StubLLM(error=RuntimeError('provider down')), 'm', seed)) \
        == 'Refactor the calendar'
    assert run(thread_naming.generate_title(StubLLM(text=''), 'm', seed)) \
        == 'Refactor the calendar'
    assert run(thread_naming.generate_title(StubLLM(text='   ...'), 'm', seed)) \
        == 'Refactor the calendar'


def test_generate_title_needs_something_to_name():
    assert run(thread_naming.generate_title(StubLLM(text='X'), 'm', '')) is None
    assert run(thread_naming.generate_title(StubLLM(text='X'), 'm', None)) is None


def test_seed_is_bounded():
    seed = thread_naming.seed_text('word ' * 5000)
    assert len(seed) <= thread_naming.SEED_MAX_CHARS


# ===== Wiring: the thread actually gets renamed ===============================

@pytest.fixture
def naming_env(monkeypatch):
    monkeypatch.setenv('AI_API_KEY', 'stub-key')
    monkeypatch.delenv('CHAT_AUTO_NAME', raising=False)
    monkeypatch.delenv('CHAT_TITLE_MODEL', raising=False)


def scenario(db_path, title_text, before=None):
    """Run `auto_name_thread` in a real Chainlit http context against a real
    SQLite data layer; return (thread name in the DB, emitted events, llm)."""
    import chainlit.data as cl_data
    from chainlit.context import context_var, init_http_context

    layer = build_data_layer(db_path)
    llm = StubLLM(text=title_text)
    emitted = []

    async def go():
        previous = cl_data._data_layer
        cl_data._data_layer = layer
        try:
            user = await layer.create_user(User(identifier='owner'))
            thread_id = str(uuid.uuid4())
            await layer.update_thread(
                thread_id, name='Can you help me plan the next sprint?',
                user_id=user.id)
            init_http_context(thread_id=thread_id, user=user)

            class Recorder:
                async def emit(self, event, data):
                    emitted.append((event, data))

            context_var.get().emitter = Recorder()
            import chainlit as cl
            cl.user_session.set(chainlit_app.AUTO_NAME_PENDING, True)
            if before:
                before()
            await chainlit_app.auto_name_thread(
                'Can you help me plan the next sprint?', 'chat-model')
            # A second turn must not rename the chat again.
            await chainlit_app.auto_name_thread('And what about testing?',
                                                'chat-model')
            row = sqlite3.connect(db_path).execute(
                'SELECT "name" FROM threads WHERE id = ?', (thread_id,)).fetchone()
            return row[0], thread_id
        finally:
            cl_data._data_layer = previous

    name, thread_id = asyncio.run(go())
    return name, thread_id, emitted, llm


def test_auto_name_renames_the_thread_once(tmp_path, naming_env, monkeypatch):
    llm_holder = {}

    def make_llm():
        llm_holder['llm'] = StubLLM(text='Sprint planning')
        return llm_holder['llm']

    monkeypatch.setattr(chainlit_app, 'title_llm', make_llm)
    name, thread_id, emitted, _ = scenario(str(tmp_path / 'chainlit.db'), 'unused')

    assert name == 'Sprint planning'
    assert len(llm_holder['llm'].calls) == 1  # only the first turn names the chat
    # The sidebar refetches its thread list off this event.
    assert ('first_interaction',
            {'interaction': 'Sprint planning', 'thread_id': thread_id}) in emitted


def test_auto_name_uses_the_configured_title_model(tmp_path, naming_env, monkeypatch):
    monkeypatch.setenv('CHAT_TITLE_MODEL', 'tiny-model')
    seen = {}

    class Recording(StubLLM):
        async def stream_chat(self, model, system, messages, tools=None, on_text=None):
            seen['model'] = model
            return await super().stream_chat(model, system, messages, tools, on_text)

    monkeypatch.setattr(chainlit_app, 'title_llm', lambda: Recording(text='Sprint plan'))
    scenario(str(tmp_path / 'chainlit.db'), 'unused')
    assert seen['model'] == 'tiny-model'

    monkeypatch.delenv('CHAT_TITLE_MODEL')
    seen.clear()
    scenario(str(tmp_path / 'chainlit2.db'), 'unused')
    assert seen['model'] == 'chat-model'  # the model the conversation runs on


def test_auto_name_can_be_switched_off(tmp_path, naming_env, monkeypatch):
    monkeypatch.setenv('CHAT_AUTO_NAME', '0')
    monkeypatch.setattr(chainlit_app, 'title_llm',
                        lambda: StubLLM(text='Sprint planning'))
    name, _, emitted, _ = scenario(str(tmp_path / 'chainlit.db'), 'unused')

    assert name == 'Can you help me plan the next sprint?'  # Chainlit's default
    assert emitted == []


def test_auto_name_survives_a_broken_data_layer(tmp_path, naming_env, monkeypatch):
    """A failing rename must never bubble into the conversation."""
    monkeypatch.setattr(chainlit_app, 'title_llm',
                        lambda: StubLLM(text='Sprint planning'))

    async def boom(*a, **k):
        raise RuntimeError('db gone')

    def break_layer():
        import chainlit.data as cl_data
        cl_data._data_layer.update_thread = boom

    name, _, _, _ = scenario(str(tmp_path / 'chainlit.db'), 'unused',
                             before=break_layer)
    assert name == 'Can you help me plan the next sprint?'


def test_resumed_threads_keep_their_name():
    """on_chat_resume clears the pending flag; on_chat_start sets it."""
    import inspect
    source = inspect.getsource(chainlit_app.on_chat_resume)
    assert f"set({chainlit_app.AUTO_NAME_PENDING!r}" not in source  # uses the constant
    assert 'AUTO_NAME_PENDING, False' in source
    assert 'AUTO_NAME_PENDING, True' in inspect.getsource(chainlit_app.on_chat_start)


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv('CHAT_AUTO_NAME', raising=False)
    assert settings.auto_name_chats() is True
    monkeypatch.setenv('CHAT_AUTO_NAME', '0')
    assert settings.auto_name_chats() is False
    monkeypatch.delenv('CHAT_TITLE_MODEL', raising=False)
    assert settings.title_model() is None
    monkeypatch.setenv('CHAT_TITLE_MODEL', 'tiny')
    assert settings.title_model() == 'tiny'
