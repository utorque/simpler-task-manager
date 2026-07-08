"""sandbox/tools.py — the sandbox's file + execution primitives.

These run for real (subprocesses, tmp workspaces): the functions are shared
verbatim by the dockerized sidecar and the local fallback, so what passes
here is what the agent gets.
"""

import pytest

from sandbox import tools


@pytest.fixture
def ws(tmp_path):
    return str(tmp_path)


# ===== path safety ============================================================

def test_safe_path_allows_inside(ws):
    assert tools.safe_path(ws, 'a/b.txt').endswith('a/b.txt')
    assert tools.safe_path(ws, '.') == tools.safe_path(ws, '')


@pytest.mark.parametrize('hostile', ['../x', '../../etc/passwd', '/etc/passwd',
                                     'a/../../x'])
def test_safe_path_rejects_escapes(ws, hostile):
    with pytest.raises(ValueError):
        tools.safe_path(ws, hostile)


# ===== file primitives ========================================================

def test_write_read_list_delete_roundtrip(ws):
    assert 'wrote' in tools.write_file(ws, 'out/data.txt', 'payload')
    assert tools.read_file(ws, 'out/data.txt') == 'payload'
    assert 'out/data.txt (7 bytes)' in tools.list_files(ws)
    assert 'deleted' in tools.delete_file(ws, 'out/data.txt')
    assert '(no such path: out/data.txt)' in tools.list_files(ws, 'out/data.txt')


def test_read_binary_flagged(ws):
    with open(tools.safe_path(ws, 'blob.bin'), 'wb') as f:
        f.write(b'\xff\xfe\x00binary')
    assert 'binary file' in tools.read_file(ws, 'blob.bin')


def test_delete_workspace_root_refused(ws):
    with pytest.raises(ValueError):
        tools.delete_file(ws, '.')


def test_list_hides_dotfiles(ws):
    tools.write_file(ws, '.hidden', 'x')
    tools.write_file(ws, 'shown.txt', 'x')
    listing = tools.list_files(ws)
    assert 'shown.txt' in listing and '.hidden' not in listing


# ===== execution ==============================================================

def test_run_python_stdout_and_files(ws):
    output = tools.run_python(ws, "print('hi'); open('made.txt','w').write('done')")
    assert 'exit code: 0' in output and 'hi' in output
    assert tools.read_file(ws, 'made.txt') == 'done'
    # the snippet's temp script does not linger
    assert 'snippet' not in tools.list_files(ws)


def test_run_python_error_reported(ws):
    output = tools.run_python(ws, 'raise RuntimeError("boom")')
    assert 'exit code: 1' in output and 'boom' in output


def test_run_python_timeout(ws):
    output = tools.run_python(ws, 'import time; time.sleep(5)', timeout=1)
    assert 'TIMEOUT' in output


def test_run_shell(ws):
    tools.write_file(ws, 'x.txt', 'abc')
    output = tools.run_shell(ws, 'ls && cat x.txt')
    assert 'exit code: 0' in output and 'x.txt' in output and 'abc' in output


def test_output_truncated(ws):
    output = tools.run_python(ws, "print('y' * 100000)")
    assert 'truncated' in output
    assert len(output) < tools.MAX_OUTPUT_CHARS + 200
