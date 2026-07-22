"""The assistant's toolbox: one flat, namespaced tool table per message turn.

Merges tools from pre-integrated MCP servers (chat/mcp_tools.py), MCP
sessions the user added through Chainlit's UI, and native in-process tools
(web search, etc.). The agent loop (chat/agent.py) only ever sees this:
`specs()` for the model, `execute(name, args)` for the calls.
"""

import inspect


class Toolbox:
    def __init__(self):
        self._specs: list[dict] = []
        self._executors: dict = {}

    def specs(self) -> list[dict]:
        return list(self._specs)

    def _register(self, spec: dict, executor):
        if spec['name'] in self._executors:
            return  # first registration wins (pre-integrated before UI-added)
        self._specs.append(spec)
        self._executors[spec['name']] = executor

    def add_native(self, name: str, description: str, input_schema: dict, fn):
        """Register an in-process tool. `fn(**arguments)` (sync or async)
        must return a string."""
        async def executor(arguments):
            result = fn(**(arguments or {}))
            if inspect.isawaitable(result):
                result = await result
            return str(result)
        self._register({'name': name, 'description': description,
                        'input_schema': input_schema}, executor)

    async def add_mcp_server(self, server) -> int:
        """Register every tool of a pre-integrated MCPToolServer."""
        specs = await server.list_tool_specs()
        for spec in specs:
            bare_name = spec['name'].split('__', 1)[1]
            def executor(arguments, _name=bare_name, _server=server):
                return _server.call_tool(_name, arguments)
            self._register(spec, executor)
        return len(specs)

    def add_mcp_session(self, server_name: str, session, tool_specs: list[dict]):
        """Register tools of a live (Chainlit-managed) MCP ClientSession.
        `tool_specs` were listed at connect time (see on_mcp_connect)."""
        from chat.mcp_tools import result_to_text

        for spec in tool_specs:
            bare_name = spec['name'].split('__', 1)[1]
            async def executor(arguments, _name=bare_name, _session=session):
                result = await _session.call_tool(_name, arguments or {})
                return result_to_text(result)
            self._register(spec, executor)

    async def execute(self, name: str, arguments: dict) -> str:
        executor = self._executors.get(name)
        if executor is None:
            return f'TOOL ERROR: unknown tool {name!r}'
        try:
            return await executor(arguments)
        except Exception as e:
            # The model gets the failure as data and can retry/adapt; the
            # turn must not crash on a flaky tool.
            return f'TOOL ERROR: {e}'
