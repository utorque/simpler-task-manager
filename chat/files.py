"""File plumbing for the assistant: uploads in, deliveries out.

In: message attachments become model context — text-like files are inlined
(fenced, truncated at MAX_INLINE_CHARS), everything is stored in the shared
file workspace (settings.files_dir()) so tools can operate on them.

Out (issue 003.10): the model delivers files EXPLICITLY — the
`attach_file_to_answer` tool queues a workspace file for a rich download
chip after the turn (no more auto-attaching every file the turn touched),
and the system prompt documents the inline-link URL convention
(`/api/workspace/files/workspace/<rel>`, served by src/routes/workspace.py).

`resolve_under()` is the shared traversal gate for both the tool and the
workspace blueprint.
"""

import os
import re
import shutil

MAX_INLINE_CHARS = 24_000

ATTACH_FILE_SCHEMA = {
    'type': 'object',
    'properties': {
        'path': {'type': 'string',
                 'description': 'Path of a file in the shared workspace, '
                                'relative to the workspace root (absolute '
                                'in-workspace paths also accepted)'},
    },
    'required': ['path'],
}


def resolve_under(root: str, path: str) -> str | None:
    """Canonicalized absolute path of `path` inside `root`, or None when it
    escapes (traversal, out-of-root absolute path, out-of-root symlink,
    null byte, backslash). The single traversal check shared by the
    attach_file_to_answer tool and the /api/workspace blueprint."""
    path = path or ''
    if not path or '\0' in path or '\\' in path:
        return None
    root_real = os.path.realpath(root)
    candidate = path if os.path.isabs(path) else os.path.join(root_real, path)
    full = os.path.realpath(candidate)
    if full != root_real and not full.startswith(root_real + os.sep):
        return None
    return full


def register(toolbox, store_dir: str, queue: list):
    """Register `attach_file_to_answer`: validates the path against the
    workspace root and appends it to `queue` — the caller (on_message)
    flushes the queue as cl.File chips once the agent's turn ends."""
    def attach_file_to_answer(path: str) -> str:
        full = resolve_under(store_dir, path)
        if full is None:
            return ('TOOL ERROR: that path is outside the shared workspace — '
                    'only files under the workspace root can be attached.')
        if not os.path.isfile(full):
            return f'TOOL ERROR: file not found: {path}'
        if full not in queue:
            queue.append(full)
        size = os.path.getsize(full)
        return (f'File queued for delivery: {os.path.basename(full)} '
                f'({size} bytes). It will be attached to your answer as a '
                'download chip when your turn ends.')

    toolbox.add_native(
        'attach_file_to_answer',
        'Deliver a workspace file to the user as a rich download chip '
        'attached to your answer. Use it only for files the user should '
        'receive — scratch/intermediate files are never auto-surfaced.',
        ATTACH_FILE_SCHEMA, attach_file_to_answer)


def _safe_name(name: str) -> str:
    base = os.path.basename(name or 'file')
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base) or 'file'


def _unique_path(directory: str, name: str) -> str:
    stem, ext = os.path.splitext(_safe_name(name))
    candidate = os.path.join(directory, stem + ext)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f'{stem}-{counter}{ext}')
        counter += 1
    return candidate


def read_text(path: str):
    """File content as text, or None when it isn't valid UTF-8."""
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return None


def ingest_file(name: str, path: str, mime: str | None, store_dir: str) -> str:
    """One attachment -> one markdown context block. Every file is ALSO
    stored in the workspace so file tools can reach it later; text content
    is additionally inlined for the model."""
    os.makedirs(store_dir, exist_ok=True)
    stored = _unique_path(store_dir, name)
    try:
        shutil.copyfile(path, stored)
    except OSError as e:
        return f'(attachment {name!r} could not be stored: {e})'
    size = os.path.getsize(stored)

    header = (f'### Attached file: {name}\n'
              f'*mime: {mime or "unknown"} · {size} bytes · stored at `{stored}`*')

    # UTF-8 decodability is the inlining test; the mime is advisory only.
    text = read_text(stored)
    if text is None:
        return (f'{header}\n\n(binary content not inlined — use file/sandbox '
                'tools to work with it)')
    truncated = ''
    if len(text) > MAX_INLINE_CHARS:
        text = text[:MAX_INLINE_CHARS]
        truncated = f'\n… (truncated at {MAX_INLINE_CHARS} characters — full file at `{stored}`)'
    return f'{header}\n\n```\n{text}\n```{truncated}'


def snapshot_dir(root: str) -> dict[str, tuple[float, int]]:
    """{relative path: (mtime, size)} for every visible file under root —
    taken before an agent turn to detect what the turn produced."""
    state = {}
    if not os.path.isdir(root):
        return state
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in names:
            if name.startswith('.'):
                continue
            full = os.path.join(current, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            state[os.path.relpath(full, root)] = (stat.st_mtime, stat.st_size)
    return state


def new_files_since(root: str, before: dict[str, tuple[float, int]],
                    limit: int = 10) -> list[str]:
    """Absolute paths of files created or modified since `before`
    (newest last), capped at `limit`."""
    after = snapshot_dir(root)
    changed = [rel for rel, sig in after.items() if before.get(rel) != sig]
    changed.sort(key=lambda rel: after[rel][0])
    return [os.path.join(root, rel) for rel in changed[-limit:]]


def ingest_elements(elements, store_dir: str) -> str | None:
    """All file-bearing elements of a message -> one context block."""
    blocks = []
    for element in elements or []:
        path = getattr(element, 'path', None)
        if not path:
            continue
        blocks.append(ingest_file(
            getattr(element, 'name', 'file'), path,
            getattr(element, 'mime', None), store_dir))
    if not blocks:
        return None
    return '[Files attached by the user]\n\n' + '\n\n'.join(blocks)
