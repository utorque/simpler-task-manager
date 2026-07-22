"""Issue 003.08 — the /api/workspace/* blueprint.

Serves the assistant-workspace volume (and, by design, future roots like the
instance skills dir) over HTTP: tree listing, mkdir, upload, download, text
save, delete, move. The download route is ALSO the URL convention the model
emits for inline links, so path-traversal hardening is the security core.
"""

import io
import os

import pytest

from conftest import login


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    """Point the 'workspace' root at a temp dir (CHAT_FILES_DIR is read at
    call time by chat.settings.files_dir())."""
    root = tmp_path / 'workspace'
    root.mkdir()
    monkeypatch.setenv('CHAT_FILES_DIR', str(root))
    return root


@pytest.fixture
def wclient(client, workspace_root):
    login(client)
    return client


def test_tree_listing_workspace_root(wclient, workspace_root):
    (workspace_root / 'report.pdf').write_bytes(b'%PDF fake')
    (workspace_root / 'reports').mkdir()

    response = wclient.get('/api/workspace/tree?root=workspace')
    assert response.status_code == 200
    entries = {e['name']: e for e in response.get_json()['entries']}
    assert entries['report.pdf']['type'] == 'file'
    assert entries['report.pdf']['size'] == len(b'%PDF fake')
    assert 'mtime' in entries['report.pdf']
    assert entries['report.pdf']['url'] == '/api/workspace/files/workspace/report.pdf'
    assert entries['reports']['type'] == 'dir'
    assert 'url' not in entries['reports']


def test_tree_listing_with_subpath(wclient, workspace_root):
    (workspace_root / 'reports').mkdir()
    (workspace_root / 'reports' / 'q3.md').write_text('# Q3')

    response = wclient.get('/api/workspace/tree?root=workspace&path=reports')
    assert response.status_code == 200
    entries = response.get_json()['entries']
    assert [e['name'] for e in entries] == ['q3.md']
    assert entries[0]['url'] == '/api/workspace/files/workspace/reports/q3.md'

    assert wclient.get('/api/workspace/tree?root=workspace&path=missing').status_code == 404


def test_unknown_root_rejected(wclient):
    assert wclient.get('/api/workspace/tree?root=foo').status_code == 400


def test_path_traversal_rejected(wclient, workspace_root):
    (workspace_root / 'reports').mkdir()
    attacks = ['../../etc/passwd', '/etc/passwd', 'reports/../../etc/passwd',
               '..', '../', 'reports/../..', '..\\..\\etc']
    for attack in attacks:
        response = wclient.get('/api/workspace/tree',
                               query_string={'root': 'workspace', 'path': attack})
        assert response.status_code == 400, attack
        # follow_redirects: Flask 308-normalizes double slashes; what matters
        # is where the normalized URL lands (inside the root or rejected).
        response = wclient.get(f'/api/workspace/files/workspace/{attack}',
                               follow_redirects=True)
        assert response.status_code in (400, 404), attack
    # Null byte
    response = wclient.get('/api/workspace/tree',
                           query_string={'root': 'workspace', 'path': 'a\0b'})
    assert response.status_code == 400
    # A symlink escaping the root is refused even though its relpath looks clean.
    outside = workspace_root.parent / 'outside.txt'
    outside.write_text('secret')
    os.symlink(outside, workspace_root / 'link.txt')
    assert wclient.get('/api/workspace/files/workspace/link.txt').status_code == 400


def test_mkdir(wclient, workspace_root):
    response = wclient.post('/api/workspace/mkdir',
                            json={'root': 'workspace', 'path': 'reports/new'})
    assert response.status_code == 201
    assert (workspace_root / 'reports' / 'new').is_dir()
    # Idempotent.
    assert wclient.post('/api/workspace/mkdir',
                        json={'root': 'workspace', 'path': 'reports/new'}).status_code == 201
    assert wclient.post('/api/workspace/mkdir',
                        json={'root': 'workspace', 'path': '../evil'}).status_code == 400


def test_upload_file(wclient, workspace_root):
    response = wclient.post(
        '/api/workspace/upload',
        data={'root': 'workspace', 'path': '',
              'file': (io.BytesIO(b'hello'), 'uploaded.txt')},
        content_type='multipart/form-data')
    assert response.status_code == 200
    assert response.get_json()['url'] == '/api/workspace/files/workspace/uploaded.txt'
    assert (workspace_root / 'uploaded.txt').read_bytes() == b'hello'

    # Into a subdir + filename sanitized to its basename.
    (workspace_root / 'sub').mkdir()
    response = wclient.post(
        '/api/workspace/upload',
        data={'root': 'workspace', 'path': 'sub',
              'file': (io.BytesIO(b'x'), '../escape.txt')},
        content_type='multipart/form-data')
    assert response.status_code == 200
    assert (workspace_root / 'sub' / 'escape.txt').exists()
    assert not (workspace_root / 'escape.txt').exists()


def test_download_file(wclient, workspace_root):
    (workspace_root / 'reports').mkdir()
    (workspace_root / 'reports' / 'foo.pdf').write_bytes(b'%PDF bytes')
    response = wclient.get('/api/workspace/files/workspace/reports/foo.pdf')
    assert response.status_code == 200
    assert response.data == b'%PDF bytes'
    assert 'attachment' in response.headers['Content-Disposition']
    assert 'foo.pdf' in response.headers['Content-Disposition']

    (workspace_root / 'notes.md').write_text('# hi')
    response = wclient.get('/api/workspace/files/workspace/notes.md')
    assert response.status_code == 200
    assert response.mimetype in ('text/markdown', 'text/plain')
    assert 'inline' in response.headers.get('Content-Disposition', 'inline')

    assert wclient.get('/api/workspace/files/workspace/missing.bin').status_code == 404


def test_save_text_file(wclient, workspace_root):
    response = wclient.put('/api/workspace/file',
                           json={'root': 'workspace', 'path': 'notes.md',
                                 'content': '# hi'})
    assert response.status_code == 200
    assert (workspace_root / 'notes.md').read_text() == '# hi'
    # Overwrite + parent dirs created.
    wclient.put('/api/workspace/file',
                json={'root': 'workspace', 'path': 'deep/dir/notes.md',
                      'content': 'nested'})
    assert (workspace_root / 'deep' / 'dir' / 'notes.md').read_text() == 'nested'


def test_delete_file(wclient, workspace_root):
    (workspace_root / 'notes.md').write_text('x')
    response = wclient.delete(
        '/api/workspace/file?root=workspace&path=notes.md')
    assert response.status_code == 200
    assert not (workspace_root / 'notes.md').exists()
    assert wclient.delete(
        '/api/workspace/file?root=workspace&path=notes.md').status_code == 404
    # Deleting the root itself is refused.
    assert wclient.delete(
        '/api/workspace/file?root=workspace&path=').status_code == 400


def test_delete_folder_recurses(wclient, workspace_root):
    (workspace_root / 'dir' / 'sub').mkdir(parents=True)
    (workspace_root / 'dir' / 'sub' / 'f.txt').write_text('x')
    response = wclient.delete('/api/workspace/file?root=workspace&path=dir')
    assert response.status_code == 200
    assert not (workspace_root / 'dir').exists()


def test_move_file(wclient, workspace_root):
    (workspace_root / 'a.txt').write_text('content')
    response = wclient.post('/api/workspace/move',
                            json={'root': 'workspace',
                                  'from': 'a.txt', 'to': 'sub/a.txt'})
    assert response.status_code == 200
    assert (workspace_root / 'sub' / 'a.txt').read_text() == 'content'
    assert not (workspace_root / 'a.txt').exists()
    # Traversal on either side is refused.
    assert wclient.post('/api/workspace/move',
                        json={'root': 'workspace', 'from': 'sub/a.txt',
                              'to': '../out.txt'}).status_code == 400
    assert wclient.post('/api/workspace/move',
                        json={'root': 'workspace', 'from': 'missing.txt',
                              'to': 'b.txt'}).status_code == 404


def test_skills_root_allowlisted(wclient, tmp_path, monkeypatch):
    """The 'skills' root exists in the allowlist (future file-browser use)."""
    from chat import settings as chat_settings
    monkeypatch.setattr(chat_settings, 'INSTANCE_DIR', str(tmp_path / 'inst'))
    response = wclient.get('/api/workspace/tree?root=skills')
    assert response.status_code == 200
    assert response.get_json()['entries'] == []


def test_auth_required(client, workspace_root):
    routes = [
        ('get', '/api/workspace/tree?root=workspace', None),
        ('post', '/api/workspace/mkdir', {'root': 'workspace', 'path': 'x'}),
        ('get', '/api/workspace/files/workspace/a.txt', None),
        ('put', '/api/workspace/file',
         {'root': 'workspace', 'path': 'a.txt', 'content': ''}),
        ('delete', '/api/workspace/file?root=workspace&path=a.txt', None),
        ('post', '/api/workspace/move',
         {'root': 'workspace', 'from': 'a', 'to': 'b'}),
    ]
    for method, url, body in routes:
        response = getattr(client, method)(url, json=body) if body is not None \
            else getattr(client, method)(url)
        assert response.status_code == 401, url
    response = client.post('/api/workspace/upload', data={'root': 'workspace'},
                           content_type='multipart/form-data')
    assert response.status_code == 401


# ===== Issue 003.09: WorkspaceView contract ===================================

def test_tree_endpoint_shape_matches_view_contract(wclient, workspace_root):
    """workspace.js renders exactly these fields; files carry the download
    url, dirs don't."""
    (workspace_root / 'docs').mkdir()
    (workspace_root / 'a.txt').write_text('x')
    payload = wclient.get('/api/workspace/tree?root=workspace').get_json()
    assert set(payload.keys()) == {'root', 'path', 'entries'}
    for entry in payload['entries']:
        expected = {'name', 'type', 'size', 'mtime'}
        if entry['type'] == 'file':
            expected.add('url')
        assert set(entry.keys()) == expected
    # Dirs sort before files.
    assert [e['name'] for e in payload['entries']] == ['docs', 'a.txt']


def test_invalid_chars_in_path_rejected_server_side(wclient):
    for bad in ('a\0b.txt', '..', 'x/../../y', '\\evil', 'a\\b'):
        response = wclient.put('/api/workspace/file',
                               json={'root': 'workspace', 'path': bad,
                                     'content': 'x'})
        assert response.status_code == 400, bad
        response = wclient.post('/api/workspace/mkdir',
                                json={'root': 'workspace', 'path': bad})
        assert response.status_code == 400, bad


def test_inline_md_edit_roundtrip(wclient, workspace_root):
    """PUT then GET returns the exact bytes (no encoding drift) — the
    autosave-on-blur cycle of the inline editor."""
    content = '# Héllo\n\n- ünicode & <html> “quotes”\n\n```py\nx = 1\n```\n'
    assert wclient.put('/api/workspace/file',
                       json={'root': 'workspace', 'path': 'notes/inline.md',
                             'content': content}).status_code == 200
    response = wclient.get('/api/workspace/files/workspace/notes/inline.md')
    assert response.status_code == 200
    assert response.data.decode('utf-8') == content
