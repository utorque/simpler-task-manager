"""The agent loop: model ⇄ tools until the model stops calling tools.

UI-free by design — `hooks` receives every observable event (text deltas,
round ends, tool starts/ends) and the Chainlit layer renders them; tests
record them. The transcript grows in the canonical OpenAI-style format the
provider adapter (chat/providers.py) consumes for both wire formats.
"""

from chat.providers import ChatResult, ToolCall  # noqa: F401  (re-export for hooks impls)

MAX_ROUNDS_NOTE = (
    'Stopped after the maximum number of tool rounds — summarize what was '
    'done so far and ask the user how to continue.')


class AgentHooks:
    """Override what you need; defaults are no-ops."""

    async def on_text(self, delta: str): ...

    async def on_round_end(self, result): ...

    async def on_tool_start(self, call): ...

    async def on_tool_end(self, call, output: str): ...


async def run_agent(llm, model: str, system: str, history: list[dict],
                    toolbox, hooks: AgentHooks, max_rounds: int = 8) -> list[dict]:
    """Run tool rounds until the model answers without tool calls (or the
    round budget runs out). Returns the full transcript including tool
    traffic (the caller's history list is not mutated)."""
    messages = list(history)
    specs = toolbox.specs()

    for round_index in range(max_rounds):
        result = await llm.stream_chat(
            model=model,
            system=system,
            messages=messages,
            tools=specs or None,
            on_text=hooks.on_text,
        )
        await hooks.on_round_end(result)
        if not result.tool_calls:
            messages.append(result.to_assistant_message())
            return messages

        messages.append(result.to_assistant_message())
        for call in result.tool_calls:
            await hooks.on_tool_start(call)
            output = await toolbox.execute(call.name, call.arguments)
            await hooks.on_tool_end(call, output)
            messages.append({
                'role': 'tool',
                'tool_call_id': call.id,
                'content': output,
            })

    # Budget exhausted with tool calls still pending: one last text-only
    # round so the user gets a coherent wrap-up instead of silence.
    messages.append({'role': 'user', 'content': MAX_ROUNDS_NOTE})
    result = await llm.stream_chat(
        model=model, system=system, messages=messages, on_text=hooks.on_text)
    await hooks.on_round_end(result)
    messages.append(result.to_assistant_message())
    return messages
