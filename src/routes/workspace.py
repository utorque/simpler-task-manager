"""Workspace file API: the assistant's file volume over HTTP.

Serves the `assistant-workspace` volume (shared web ⇄ sandbox) to the
sidebar view (`WorkspaceView`, issue 003.09) and to the model's inline
download links (`/api/workspace/files/<root>/<path>` is the sanctioned URL
convention, issue 003.10).

Multi-root by design: `root` names an allowlisted directory. Every path is
canonicalized (`os.path.realpath`) and must stay under its root — the
download route is reachable by URL, so traversal hardening here is the
security core of Bundle C.
"""

import mimetypes
import os
import shutil

from flask import Blueprint, jsonify, request, send_file

from auth import login_required

from chat import assistant_settings
from chat import settings as chat_settings

workspace_bp = Blueprint('workspace', __name__)

# root name -> directory factory (called per request: env/instance paths may
# be redirected at runtime, e.g. in tests). 'skills' is allowlisted for the
# future skills-file-browser enhancement; the 003.09 sidebar only uses
# 'workspace'.
ROOTS = {
    'workspace': lambda: chat_settings.files_dir(),
    'skills': lambda: assistant_settings.instance_skills_dir(),
}

TEXT_MIMES = {'.md': 'text/markdown', '.txt': 'text/plain'}


def resolve_in_root(root: str, relpath: str):
    """(root_dir, full_path) with both canonicalized, or None when the root
    is not allowlisted or the path escapes it (traversal, absolute path,
    null byte, out-of-root symlink)."""
    factory = ROOTS.get(root or '')
    if factory is None:
        return None
    relpath = relpath or ''
    # Backslashes are legal Linux filename chars but path separators on
    # Windows clients — reject outright (defense in depth).
    if '\0' in relpath or '\\' in relpath or relpath.startswith('/'):
        return None
    root_dir = os.path.realpath(factory())
    full = os.path.realpath(os.path.join(root_dir, relpath))
    if full != root_dir and not full.startswith(root_dir + os.sep):
        return None
    return root_dir, full


def _bad_path():
    return jsonify({'error': 'unknown root or path outside the workspace'}), 400


def _entry(full: str, root: str, root_dir: str) -> dict:
    stat = os.stat(full)
    entry = {
        'name': os.path.basename(full),
        'type': 'dir' if os.path.isdir(full) else 'file',
        'size': stat.st_size,
        'mtime': stat.st_mtime,
    }
    if entry['type'] == 'file':
        rel = os.path.relpath(full, root_dir).replace(os.sep, '/')
        entry['url'] = f'/api/workspace/files/{root}/{rel}'
    return entry


@workspace_bp.route('/api/workspace/tree', methods=['GET'])
@login_required
def workspace_tree():
    root = request.args.get('root', '')
    resolved = resolve_in_root(root, request.args.get('path', ''))
    if resolved is None:
        return _bad_path()
    root_dir, full = resolved
    if not os.path.isdir(full):
        return jsonify({'error': 'no such directory'}), 404
    entries = []
    for name in sorted(os.listdir(full)):
        if name.startswith('.'):
            continue
        try:
            entries.append(_entry(os.path.join(full, name), root, root_dir))
        except OSError:
            continue
    # Folders first, then files, both alphabetical.
    entries.sort(key=lambda e: (e['type'] != 'dir', e['name'].lower()))
    rel = os.path.relpath(full, root_dir).replace(os.sep, '/')
    return jsonify({'root': root, 'path': '' if rel == '.' else rel,
                    'entries': entries})


@workspace_bp.route('/api/workspace/mkdir', methods=['POST'])
@login_required
def workspace_mkdir():
    data = request.json or {}
    resolved = resolve_in_root(data.get('root', ''), data.get('path', ''))
    if resolved is None:
        return _bad_path()
    root_dir, full = resolved
    if full == root_dir:
        return _bad_path()
    if os.path.isfile(full):
        return jsonify({'error': 'a file with that name exists'}), 409
    os.makedirs(full, exist_ok=True)
    return jsonify({'ok': True}), 201


def _max_upload_bytes() -> int:
    return int(os.getenv('WORKSPACE_MAX_UPLOAD_MB', '100')) * 1024 * 1024


@workspace_bp.route('/api/workspace/upload', methods=['POST'])
@login_required
def workspace_upload():
    if (request.content_length or 0) > _max_upload_bytes():
        return jsonify({'error': 'file too large'}), 413
    root = request.form.get('root', '')
    resolved = resolve_in_root(root, request.form.get('path', ''))
    if resolved is None:
        return _bad_path()
    root_dir, target_dir = resolved
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify({'error': 'no file in the request'}), 400
    # The filename is client-controlled: keep only its basename.
    name = os.path.basename(upload.filename.replace('\\', '/'))
    if not name or name.startswith('.'):
        return jsonify({'error': 'invalid filename'}), 400
    os.makedirs(target_dir, exist_ok=True)
    full = os.path.join(target_dir, name)
    upload.save(full)
    rel = os.path.relpath(full, root_dir).replace(os.sep, '/')
    return jsonify({'ok': True, 'url': f'/api/workspace/files/{root}/{rel}'})


@workspace_bp.route('/api/workspace/files/<root>/<path:rest>', methods=['GET'])
@login_required
def workspace_download(root, rest):
    resolved = resolve_in_root(root, rest)
    if resolved is None:
        return _bad_path()
    _, full = resolved
    if not os.path.isfile(full):
        return jsonify({'error': 'no such file'}), 404
    ext = os.path.splitext(full)[1].lower()
    mime = TEXT_MIMES.get(ext) or mimetypes.guess_type(full)[0] \
        or 'application/octet-stream'
    # Text renders inline (the sidebar's editor fetches it); everything else
    # downloads.
    inline = mime.startswith('text/')
    return send_file(full, mimetype=mime, as_attachment=not inline,
                     download_name=os.path.basename(full))


@workspace_bp.route('/api/workspace/file', methods=['PUT'])
@login_required
def workspace_save_file():
    data = request.json or {}
    resolved = resolve_in_root(data.get('root', ''), data.get('path', ''))
    if resolved is None:
        return _bad_path()
    root_dir, full = resolved
    if full == root_dir or os.path.isdir(full):
        return _bad_path()
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(data.get('content', ''))
    return jsonify({'ok': True})


@workspace_bp.route('/api/workspace/file', methods=['DELETE'])
@login_required
def workspace_delete():
    resolved = resolve_in_root(request.args.get('root', ''),
                               request.args.get('path', ''))
    if resolved is None:
        return _bad_path()
    root_dir, full = resolved
    if full == root_dir:
        return _bad_path()  # never delete the root itself
    if os.path.isdir(full):
        shutil.rmtree(full)
    elif os.path.isfile(full):
        os.remove(full)
    else:
        return jsonify({'error': 'no such file or directory'}), 404
    return jsonify({'ok': True})


@workspace_bp.route('/api/workspace/move', methods=['POST'])
@login_required
def workspace_move():
    data = request.json or {}
    root = data.get('root', '')
    source = resolve_in_root(root, data.get('from', ''))
    target = resolve_in_root(root, data.get('to', ''))
    if source is None or target is None:
        return _bad_path()
    root_dir, source_full = source
    _, target_full = target
    if source_full == root_dir or target_full == root_dir:
        return _bad_path()
    if not os.path.exists(source_full):
        return jsonify({'error': 'no such file or directory'}), 404
    os.makedirs(os.path.dirname(target_full), exist_ok=True)
    shutil.move(source_full, target_full)
    return jsonify({'ok': True})
