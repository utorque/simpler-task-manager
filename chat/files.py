"""Uploaded-file ingestion: turn message attachments into model context.

Text-like files are inlined (fenced, truncated at MAX_INLINE_CHARS) so the
model can read them directly. Binary files are copied into the assistant's
file workspace (settings.files_dir(); shared with the sandbox from step 5
on) and referenced by path so tools can operate on them.
"""

import os
import re
import shutil

MAX_INLINE_CHARS = 24_000


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
