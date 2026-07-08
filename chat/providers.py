"""LLM provider adapter for the assistant: one interface, two wire formats.

Mirrors src/ai_parser.py's provider selection (`anthropic` in AI_API_BASE_URL
-> Anthropic, else any OpenAI-compatible endpoint) so the assistant follows
the exact same .env as the rest of the app, but adds what a chat agent needs
and the in-app parser doesn't: streaming and tool calls.

Canonical formats (provider-agnostic, converted per wire format here):
- messages: OpenAI chat format — {'role': 'user'|'assistant'|'tool', ...},
  assistant messages may carry 'tool_calls', tool messages carry
  'tool_call_id' + 'content'.
- tools: [{'name', 'description', 'input_schema'}] with a JSON-schema dict.

`stream_chat` streams text deltas through the `on_text` callback and returns
the assembled ChatResult (full text + parsed tool calls) once the model
stops. The Chainlit layer owns UI concerns; this module owns the wire.
"""

import json
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    text: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = 'stop'

    def to_assistant_message(self) -> dict:
        """Canonical assistant message echoing this result (for the running
        transcript when tool calls loop back into the model)."""
        message = {'role': 'assistant', 'content': self.text or ''}
        if self.tool_calls:
            message['tool_calls'] = [
                {
                    'id': call.id,
                    'type': 'function',
                    'function': {
                        'name': call.name,
                        'arguments': json.dumps(call.arguments),
                    },
                }
                for call in self.tool_calls
            ]
        return message


def provider_kind(base_url: str) -> str:
    """'anthropic' | 'openai' — same heuristic as src/ai_parser.py."""
    return 'anthropic' if 'anthropic' in (base_url or '').lower() else 'openai'


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {'_raw': raw}
    return parsed if isinstance(parsed, dict) else {'_raw': parsed}


class LLMClient:
    def __init__(self, api_key: str, base_url: str, max_tokens: int = 4096):
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.kind = provider_kind(base_url)

    async def stream_chat(self, model: str, system: str, messages: list[dict],
                          tools: list[dict] | None = None,
                          on_text=None) -> ChatResult:
        if self.kind == 'anthropic':
            return await self._stream_anthropic(model, system, messages, tools, on_text)
        return await self._stream_openai(model, system, messages, tools, on_text)

    # ----- OpenAI-compatible ------------------------------------------------

    @staticmethod
    def _openai_tools(tools):
        return [
            {
                'type': 'function',
                'function': {
                    'name': t['name'],
                    'description': t.get('description', ''),
                    'parameters': t.get('input_schema') or {'type': 'object', 'properties': {}},
                },
            }
            for t in tools
        ]

    async def _stream_openai(self, model, system, messages, tools, on_text) -> ChatResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        kwargs = {}
        if tools:
            kwargs['tools'] = self._openai_tools(tools)
        stream = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'system', 'content': system}] + messages,
            max_tokens=self.max_tokens,
            stream=True,
            **kwargs,
        )

        result = ChatResult()
        # index -> {'id', 'name', 'arguments'(str fragments)}
        pending_calls: dict[int, dict] = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                result.text += delta.content
                if on_text:
                    await on_text(delta.content)
            if delta and delta.tool_calls:
                for fragment in delta.tool_calls:
                    slot = pending_calls.setdefault(
                        fragment.index, {'id': '', 'name': '', 'arguments': ''})
                    if fragment.id:
                        slot['id'] = fragment.id
                    if fragment.function and fragment.function.name:
                        slot['name'] = fragment.function.name
                    if fragment.function and fragment.function.arguments:
                        slot['arguments'] += fragment.function.arguments
            if choice.finish_reason:
                result.finish_reason = choice.finish_reason

        for index in sorted(pending_calls):
            slot = pending_calls[index]
            result.tool_calls.append(ToolCall(
                id=slot['id'] or f'call_{index}',
                name=slot['name'],
                arguments=_parse_arguments(slot['arguments']),
            ))
        return result

    # ----- Anthropic --------------------------------------------------------

    @staticmethod
    def _anthropic_tools(tools):
        return [
            {
                'name': t['name'],
                'description': t.get('description', ''),
                'input_schema': t.get('input_schema') or {'type': 'object', 'properties': {}},
            }
            for t in tools
        ]

    @staticmethod
    def _anthropic_messages(messages) -> list[dict]:
        """Convert canonical (OpenAI-style) history to Anthropic content
        blocks. Tool results become user-role tool_result blocks; consecutive
        ones merge into a single user message as the API requires."""
        converted = []

        def push(role, blocks):
            if converted and converted[-1]['role'] == role:
                converted[-1]['content'].extend(blocks)
            else:
                converted.append({'role': role, 'content': list(blocks)})

        for message in messages:
            role = message.get('role')
            content = message.get('content') or ''
            if role == 'assistant':
                blocks = []
                if content:
                    blocks.append({'type': 'text', 'text': content})
                for call in message.get('tool_calls') or []:
                    blocks.append({
                        'type': 'tool_use',
                        'id': call['id'],
                        'name': call['function']['name'],
                        'input': _parse_arguments(call['function']['arguments']),
                    })
                if blocks:
                    push('assistant', blocks)
            elif role == 'tool':
                push('user', [{
                    'type': 'tool_result',
                    'tool_use_id': message.get('tool_call_id'),
                    'content': content,
                }])
            elif role == 'user':
                push('user', [{'type': 'text', 'text': content}])
            # System entries inside the history (rare; Chainlit context
            # injections) ride along as user text so nothing is lost.
            elif role == 'system' and content:
                push('user', [{'type': 'text', 'text': content}])
        return converted

    async def _stream_anthropic(self, model, system, messages, tools, on_text) -> ChatResult:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)
        kwargs = {}
        if tools:
            kwargs['tools'] = self._anthropic_tools(tools)
        result = ChatResult()
        async with client.messages.stream(
            model=model,
            system=system,
            messages=self._anthropic_messages(messages),
            max_tokens=self.max_tokens,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                result.text += text
                if on_text:
                    await on_text(text)
            final = await stream.get_final_message()

        for block in final.content:
            if block.type == 'tool_use':
                result.tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {'_raw': block.input},
                ))
        result.finish_reason = final.stop_reason or 'stop'
        return result
