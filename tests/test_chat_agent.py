"""chat/agent.py + chat/toolbox.py — the tool loop, with a scripted LLM."""

import asyncio

import pytest

from chat.agent import AgentHooks, run_agent
from chat.providers import ChatResult, ToolCall
from chat.toolbox import Toolbox


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    """Returns pre-scripted ChatResults; records every call it receives."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def stream_chat(self, model, system, messages, tools=None, on_text=None):
        self.calls.append({'messages': [dict(m) for m in messages], 'tools': tools})
        result = self.script.pop(0)
        if on_text and result.text:
            await on_text(result.text)
        return result


class RecordingHooks(AgentHooks):
    def __init__(self):
        self.events = []

    async def on_text(self, delta):
        self.events.append(('text', delta))

    async def on_round_end(self, result):
        self.events.append(('round_end', result.text))

    async def on_tool_start(self, call):
        self.events.append(('tool_start', call.name))

    async def on_tool_end(self, call, output):
        self.events.append(('tool_end', call.name, output))


def make_toolbox():
    toolbox = Toolbox()
    toolbox.add_native('echo', 'echo back', {'type': 'object', 'properties': {}},
                       lambda **kw: f"echo:{kw.get('value')}")
    return toolbox


def test_text_only_turn():
    llm = FakeLLM([ChatResult(text='plain answer')])
    hooks = RecordingHooks()
    transcript = run(run_agent(llm, 'm', 'sys', [{'role': 'user', 'content': 'hi'}],
                               make_toolbox(), hooks))
    assert transcript[-1] == {'role': 'assistant', 'content': 'plain answer'}
    assert ('text', 'plain answer') in hooks.events
    # Tools were offered to the model even though it didn't use them.
    assert llm.calls[0]['tools'][0]['name'] == 'echo'


def test_tool_round_then_answer():
    llm = FakeLLM([
        ChatResult(text='', tool_calls=[ToolCall(id='c1', name='echo',
                                                 arguments={'value': 42})]),
        ChatResult(text='done'),
    ])
    hooks = RecordingHooks()
    transcript = run(run_agent(llm, 'm', 'sys', [{'role': 'user', 'content': 'go'}],
                               make_toolbox(), hooks))

    # Transcript: user, assistant(tool_calls), tool result, assistant text.
    roles = [m['role'] for m in transcript]
    assert roles == ['user', 'assistant', 'tool', 'assistant']
    assert transcript[2] == {'role': 'tool', 'tool_call_id': 'c1', 'content': 'echo:42'}
    # The second model call saw the tool result.
    assert llm.calls[1]['messages'][2]['content'] == 'echo:42'
    assert ('tool_start', 'echo') in hooks.events
    assert ('tool_end', 'echo', 'echo:42') in hooks.events


def test_unknown_tool_reported_to_model_not_raised():
    llm = FakeLLM([
        ChatResult(tool_calls=[ToolCall(id='c1', name='nope', arguments={})]),
        ChatResult(text='recovered'),
    ])
    transcript = run(run_agent(llm, 'm', 'sys', [], make_toolbox(), AgentHooks()))
    tool_message = next(m for m in transcript if m['role'] == 'tool')
    assert 'TOOL ERROR' in tool_message['content']
    assert transcript[-1]['content'] == 'recovered'


def test_native_tool_exception_becomes_tool_error():
    toolbox = Toolbox()
    def boom(**kw):
        raise RuntimeError('kaput')
    toolbox.add_native('boom', 'always fails', {'type': 'object'}, boom)
    llm = FakeLLM([
        ChatResult(tool_calls=[ToolCall(id='c1', name='boom', arguments={})]),
        ChatResult(text='ok'),
    ])
    transcript = run(run_agent(llm, 'm', 'sys', [], toolbox, AgentHooks()))
    tool_message = next(m for m in transcript if m['role'] == 'tool')
    assert 'TOOL ERROR: kaput' in tool_message['content']


def test_max_rounds_forces_text_wrapup():
    always_call = lambda: ChatResult(
        tool_calls=[ToolCall(id='x', name='echo', arguments={'value': 1})])
    llm = FakeLLM([always_call(), always_call(), ChatResult(text='wrap-up')])
    transcript = run(run_agent(llm, 'm', 'sys', [], make_toolbox(), AgentHooks(),
                               max_rounds=2))
    # Final call happened WITHOUT tools (forced text round).
    assert llm.calls[-1]['tools'] is None
    assert transcript[-1] == {'role': 'assistant', 'content': 'wrap-up'}


def test_toolbox_native_async_fn_and_collision():
    toolbox = Toolbox()
    async def afn(**kw):
        return 'async-result'
    toolbox.add_native('t', 'first', {'type': 'object'}, afn)
    toolbox.add_native('t', 'second (ignored)', {'type': 'object'}, lambda **kw: 'x')
    assert len(toolbox.specs()) == 1
    assert toolbox.specs()[0]['description'] == 'first'
    assert run(toolbox.execute('t', {})) == 'async-result'
    assert 'unknown tool' in run(toolbox.execute('missing', {}))
