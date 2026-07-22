"""In-process fallback for the sandbox tools (CHAT_LOCAL_SANDBOX=1).

Same functions as the dockerized sidecar (sandbox/tools.py), executed
directly on files_dir() with NO container isolation — subprocesses run as
the app user. Meant for development without compose; production should use
the sandbox service (SANDBOX_MCP_URL), which takes precedence.

Tool names carry the same `sandbox__` prefix as the sidecar's so prompts,
skills and transcripts are identical either way.
"""

import functools

SCHEMAS = {
    'run_python': {
        'type': 'object',
        'properties': {
            'code': {'type': 'string', 'description': 'Python code to execute'},
            'timeout': {'type': 'integer', 'description': 'Seconds (default 60, max 300)'},
        },
        'required': ['code'],
    },
    'run_shell': {
        'type': 'object',
        'properties': {
            'command': {'type': 'string', 'description': 'Shell command to execute'},
            'timeout': {'type': 'integer', 'description': 'Seconds (default 60, max 300)'},
        },
        'required': ['command'],
    },
    'list_files': {
        'type': 'object',
        'properties': {'path': {'type': 'string', 'description': 'Relative path (default .)'}},
    },
    'read_file': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string'},
            'max_chars': {'type': 'integer'},
        },
        'required': ['path'],
    },
    'write_file': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string'},
            'content': {'type': 'string'},
        },
        'required': ['path', 'content'],
    },
    'delete_file': {
        'type': 'object',
        'properties': {'path': {'type': 'string'}},
        'required': ['path'],
    },
}

DESCRIPTIONS = {
    'run_python': ('Execute a Python snippet in the file workspace (LOCAL '
                   'fallback, no container). Save results as files to return '
                   'them to the user.'),
    'run_shell': 'Execute a shell command in the file workspace (LOCAL fallback).',
    'list_files': 'List workspace files (recursive, with sizes).',
    'read_file': 'Read a text file from the workspace.',
    'write_file': 'Write/overwrite a text file in the workspace.',
    'delete_file': 'Delete a file or directory inside the workspace.',
}


def register(toolbox, workspace: str):
    # Imported lazily: the fallback is opt-in (CHAT_LOCAL_SANDBOX=1) and the
    # web app must import fine without the sandbox package installed.
    from sandbox import tools

    for name in SCHEMAS:
        fn = functools.partial(getattr(tools, name), workspace)
        toolbox.add_native(f'sandbox__{name}', DESCRIPTIONS[name], SCHEMAS[name], fn)
