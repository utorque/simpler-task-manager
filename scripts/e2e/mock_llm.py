"""Mock OpenAI-compatible /v1/chat/completions for the local E2E harness.

Scripted, deterministic 'model' (port 8089):
- user msg containing E2E-TASK and no tool results yet -> tool call
  simpler__create_task
- user msg containing E2E-SANDBOX and no tool results yet -> tool call
  sandbox__run_python that writes a file into the shared workspace
- any tool result present -> streams "TOOL_OK <first line of result>"
- otherwise -> streams "MOCK_REPLY hello"
"""

import json

from flask import Flask, request, Response

app = Flask(__name__)


def chunk(delta, finish=None):
    return 'data: ' + json.dumps({
        'id': 'mock-1', 'object': 'chat.completion.chunk', 'created': 0,
        'model': 'mock',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
    }) + '\n\n'


def tool_call_chunks(name, arguments):
    yield chunk({'role': 'assistant'})
    yield chunk({'tool_calls': [{
        'index': 0, 'id': 'call_mock_1', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)},
    }]})
    yield chunk({}, finish='tool_calls')
    yield 'data: [DONE]\n\n'


def text_chunks(text):
    yield chunk({'role': 'assistant'})
    for i in range(0, len(text), 8):
        yield chunk({'content': text[i:i + 8]})
    yield chunk({}, finish='stop')
    yield 'data: [DONE]\n\n'


@app.post('/v1/chat/completions')
def completions():
    body = request.get_json(force=True)
    messages = body.get('messages', [])
    tool_results = [m for m in messages if m.get('role') == 'tool']
    last_user = next((m['content'] for m in reversed(messages)
                      if m.get('role') == 'user' and m.get('content')), '')

    if tool_results:
        head = (tool_results[-1].get('content') or '').strip().splitlines()
        gen = text_chunks('TOOL_OK ' + (head[0][:120] if head else '(empty)'))
    elif 'E2E-TASK' in last_user:
        gen = tool_call_chunks('simpler__create_task', {
            'title': 'E2E task from assistant', 'space': 'work', 'priority': 4})
    elif 'E2E-SANDBOX' in last_user:
        gen = tool_call_chunks('sandbox__run_python', {
            'code': "open('e2e_output.txt','w').write('sandbox says hi')\nprint('done')"})
    else:
        gen = text_chunks('MOCK_REPLY hello from the mock model')
    return Response(gen, mimetype='text/event-stream')


@app.get('/v1/models')
def models():
    return {'object': 'list', 'data': [{'id': 'mock-model', 'object': 'model'}]}


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8089)
