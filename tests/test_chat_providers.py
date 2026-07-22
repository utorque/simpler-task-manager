"""chat/providers.py — provider selection and wire-format conversions."""

import json

from chat.providers import (
    ChatResult,
    LLMClient,
    ToolCall,
    _parse_arguments,
    provider_kind,
)


def test_provider_kind_mirrors_ai_parser_heuristic():
    assert provider_kind('https://api.anthropic.com/') == 'anthropic'
    assert provider_kind('https://api.openai.com/v1/') == 'openai'
    assert provider_kind('https://api.mistral.ai/v1/') == 'openai'
    assert provider_kind('') == 'openai'
    assert provider_kind(None) == 'openai'


def test_parse_arguments():
    assert _parse_arguments('{"a": 1}') == {'a': 1}
    assert _parse_arguments({'a': 1}) == {'a': 1}
    assert _parse_arguments('') == {}
    assert _parse_arguments(None) == {}
    assert _parse_arguments('not json') == {'_raw': 'not json'}
    assert _parse_arguments('[1, 2]') == {'_raw': [1, 2]}


def test_chat_result_to_assistant_message_plain_text():
    result = ChatResult(text='hello')
    assert result.to_assistant_message() == {'role': 'assistant', 'content': 'hello'}


def test_chat_result_to_assistant_message_with_tool_calls():
    result = ChatResult(text='', tool_calls=[
        ToolCall(id='c1', name='list_tasks', arguments={'status': 'doing'}),
    ])
    message = result.to_assistant_message()
    assert message['role'] == 'assistant'
    call = message['tool_calls'][0]
    assert call['id'] == 'c1'
    assert call['function']['name'] == 'list_tasks'
    assert json.loads(call['function']['arguments']) == {'status': 'doing'}


def test_anthropic_message_conversion_roundtrip():
    history = [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': 'calling a tool',
         'tool_calls': [{'id': 'c1', 'type': 'function',
                         'function': {'name': 'get_task', 'arguments': '{"task_id": 3}'}}]},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"id": 3}'},
        {'role': 'tool', 'tool_call_id': 'c2', 'content': '{"id": 4}'},
        {'role': 'user', 'content': 'thanks'},
    ]
    converted = LLMClient._anthropic_messages(history)

    assert [m['role'] for m in converted] == ['user', 'assistant', 'user']
    assistant = converted[1]
    assert assistant['content'][0] == {'type': 'text', 'text': 'calling a tool'}
    tool_use = assistant['content'][1]
    assert tool_use['type'] == 'tool_use'
    assert tool_use['name'] == 'get_task'
    assert tool_use['input'] == {'task_id': 3}
    # Both tool results and the follow-up user text merge into ONE user turn
    # (Anthropic requires alternating roles).
    final_user = converted[2]
    kinds = [block['type'] for block in final_user['content']]
    assert kinds == ['tool_result', 'tool_result', 'text']
    assert final_user['content'][0]['tool_use_id'] == 'c1'


def test_openai_tool_schema_conversion():
    tools = [{'name': 'search', 'description': 'find things',
              'input_schema': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}]
    converted = LLMClient._openai_tools(tools)
    assert converted[0]['type'] == 'function'
    assert converted[0]['function']['name'] == 'search'
    assert converted[0]['function']['parameters']['properties']['q']['type'] == 'string'

    anthropic = LLMClient._anthropic_tools(tools)
    assert anthropic[0]['name'] == 'search'
    assert anthropic[0]['input_schema']['properties']['q']['type'] == 'string'
