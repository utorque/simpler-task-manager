"""File plumbing for the assistant: uploads in, deliveries out.

In: message attachments become model context — text-like files are inlined
(fenced, truncated at MAX_INLINE_CHARS), everything is stored in the shared
file workspace (settings.files_dir()) so tools can operate on them.

Out: the model delivers files by LINK, never as a raw attachment. The
`get_file_link` tool validates a workspace path and returns a ready-to-embed
markdown download link using the sanctioned URL convention
(`/api/workspace/files/workspace/<rel>`, served by src/routes/workspace.py).
The link lives in the model's reply text, so it persists in chat history
across thread reloads with no blob-storage provider — unlike Chainlit
`cl.File` elements, which need one and are dropped without it.

`resolve_under()` is the shared traversal gate for both the tool and the
workspace blueprint.
"""

import os
import re
import shutil
from urllib.parse import quote

MAX_INLINE_CHARS = 24_000

# The 'workspace' root of the /api/workspace/files/<root>/<rel> download route
# (src/routes/workspace.py ROOTS) maps to the same directory as the tool's
# store_dir (chat.settings.files_dir()), so a path relative to store_dir is
# exactly the <rel> the route expects.
WORKSPACE_URL_ROOT = 'workspace'

FILE_LINK_SCHEMA = {
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
    get_file_link tool and the /api/workspace blueprint."""
    path = path or ''
    if not path or '\0' in path or '\\' in path:
        return None
    root_real = os.path.realpath(root)
    candidate = path if os.path.isabs(path) else os.path.join(root_real, path)
    full = os.path.realpath(candidate)
    if full != root_real and not full.startswith(root_real + os.sep):
        return None
    return full


def workspace_file_url(store_dir: str, full: str) -> str:
    """Sanctioned same-origin download URL for an in-workspace file. Each path
    segment is percent-encoded (spaces, unicode, etc.) so the returned link is
    valid markdown; the `/` separators are preserved."""
    rel = os.path.relpath(full, os.path.realpath(store_dir))
    encoded = quote(rel.replace(os.sep, '/'), safe='/')
    return f'/api/workspace/files/{WORKSPACE_URL_ROOT}/{encoded}'


def register(toolbox, store_dir: str):
    """Register `get_file_link`: validates a path against the workspace root
    and returns a ready-to-embed markdown download link. The model puts the
    link in its reply text — files are delivered by link, never as raw
    Chainlit attachments (which need a blob-storage provider to persist)."""
    def get_file_link(path: str) -> str:
        full = resolve_under(store_dir, path)
        if full is None:
            return ('TOOL ERROR: that path is outside the shared workspace — '
                    'only files under the workspace root can be linked.')
        if not os.path.isfile(full):
            return f'TOOL ERROR: file not found: {path}'
        name = os.path.basename(full)
        url = workspace_file_url(store_dir, full)
        size = os.path.getsize(full)
        return (f'Download link for {name} ({size} bytes). Include this exact '
                f'markdown link in your reply so the user can download it: '
                f'[{name}]({url})')

    toolbox.add_native(
        'get_file_link',
        'Get a download link for a workspace file to give the user. Returns a '
        'markdown link you embed in your reply — this is the ONLY way to '
        'deliver a file; you cannot attach files directly. Use it only for '
        'files the user should receive, never scratch/intermediate files.',
        FILE_LINK_SCHEMA, get_file_link)


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
