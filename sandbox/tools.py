"""Sandbox tool implementations: plain functions over a workspace directory.

Every path is resolved INSIDE the workspace (escapes rejected) even though
the container itself is isolated — defense in depth, and it keeps the
in-process fallback (CHAT_LOCAL_SANDBOX=1) honest, where the only wall IS
this check plus subprocess limits.

Execution model: snippets run as subprocesses with the workspace as cwd, a
wall-clock timeout, and truncated combined output. State does not persist
between calls — files in the workspace are the way to pass data around.
"""

import os
import shutil
import subprocess
import sys
import tempfile

MAX_OUTPUT_CHARS = 20_000
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300
MAX_READ_CHARS = 40_000


def safe_path(workspace: str, path: str) -> str:
    """Resolve `path` inside the workspace; reject anything that escapes."""
    workspace = os.path.realpath(workspace)
    candidate = os.path.realpath(os.path.join(workspace, path or '.'))
    if candidate != workspace and not candidate.startswith(workspace + os.sep):
        raise ValueError(f'path {path!r} escapes the workspace')
    return candidate


def _clamp_timeout(timeout) -> int:
    return max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n… (truncated at {limit} characters)'


def _run(argv: list[str], workspace: str, timeout) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=_clamp_timeout(timeout),
        )
    except subprocess.TimeoutExpired:
        return f'TIMEOUT: execution exceeded {_clamp_timeout(timeout)}s and was killed.'
    parts = [f'exit code: {completed.returncode}']
    if completed.stdout:
        parts.append(f'--- stdout ---\n{completed.stdout}')
    if completed.stderr:
        parts.append(f'--- stderr ---\n{completed.stderr}')
    if not completed.stdout and not completed.stderr:
        parts.append('(no output)')
    return _truncate('\n'.join(parts))


def run_python(workspace: str, code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run a Python snippet with the workspace as cwd."""
    os.makedirs(workspace, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            'w', suffix='.py', dir=workspace, prefix='.snippet-',
            delete=False, encoding='utf-8') as script:
        script.write(code)
        script_path = script.name
    try:
        return _run([sys.executable, script_path], workspace, timeout)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def run_shell(workspace: str, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run a shell command with the workspace as cwd."""
    os.makedirs(workspace, exist_ok=True)
    return _run(['/bin/sh', '-c', command], workspace, timeout)


def list_files(workspace: str, path: str = '.') -> str:
    root = safe_path(workspace, path)
    if not os.path.exists(root):
        return f'(no such path: {path})'
    if os.path.isfile(root):
        return f'{path} ({os.path.getsize(root)} bytes)'
    lines = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        rel = os.path.relpath(current, workspace)
        for name in sorted(names):
            if name.startswith('.'):
                continue
            full = os.path.join(current, name)
            rel_name = os.path.normpath(os.path.join(rel, name))
            lines.append(f'{rel_name} ({os.path.getsize(full)} bytes)')
        if len(lines) > 500:
            lines.append('… (listing capped at 500 entries)')
            break
    return '\n'.join(lines) or '(empty)'


def read_file(workspace: str, path: str, max_chars: int = MAX_READ_CHARS) -> str:
    full = safe_path(workspace, path)
    try:
        with open(full, encoding='utf-8') as f:
            content = f.read(max_chars + 1)
    except UnicodeDecodeError:
        return (f'(binary file, {os.path.getsize(full)} bytes — '
                'process it with run_python instead)')
    except OSError as e:
        return f'(cannot read {path}: {e})'
    return _truncate(content, max_chars)


def write_file(workspace: str, path: str, content: str) -> str:
    full = safe_path(workspace, path)
    os.makedirs(os.path.dirname(full) or workspace, exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)
    return f'wrote {len(content.encode())} bytes to {path}'


def delete_file(workspace: str, path: str) -> str:
    full = safe_path(workspace, path)
    if full == os.path.realpath(workspace):
        raise ValueError('refusing to delete the workspace root')
    if os.path.isdir(full):
        shutil.rmtree(full)
        return f'deleted directory {path}'
    os.unlink(full)
    return f'deleted {path}'
