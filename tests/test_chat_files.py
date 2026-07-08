"""chat/files.py — uploaded-file ingestion into model context."""

import os

from chat.files import MAX_INLINE_CHARS, ingest_elements, ingest_file


class FakeElement:
    def __init__(self, name, path, mime=None):
        self.name = name
        self.path = path
        self.mime = mime


def test_text_file_inlined_and_stored(tmp_path):
    src = tmp_path / 'notes.txt'
    src.write_text('hello file world')
    store = tmp_path / 'store'

    block = ingest_file('notes.txt', str(src), 'text/plain', str(store))
    assert 'hello file world' in block
    assert 'notes.txt' in block
    assert os.path.exists(store / 'notes.txt')


def test_binary_file_stored_not_inlined(tmp_path):
    src = tmp_path / 'img.png'
    src.write_bytes(b'\x89PNG\x00\xff\xfe binary')
    store = tmp_path / 'store'

    block = ingest_file('img.png', str(src), 'image/png', str(store))
    assert 'binary content not inlined' in block
    assert os.path.exists(store / 'img.png')


def test_long_text_truncated(tmp_path):
    src = tmp_path / 'big.txt'
    src.write_text('x' * (MAX_INLINE_CHARS + 500))
    block = ingest_file('big.txt', str(src), 'text/plain', str(tmp_path / 's'))
    assert 'truncated' in block
    assert len(block) < MAX_INLINE_CHARS + 600


def test_name_collision_gets_unique_path(tmp_path):
    a = tmp_path / 'a.txt'
    a.write_text('first')
    b = tmp_path / 'b.txt'
    b.write_text('second')
    store = str(tmp_path / 'store')

    ingest_file('same.txt', str(a), None, store)
    block = ingest_file('same.txt', str(b), None, store)
    assert 'same-1.txt' in block
    assert (tmp_path / 'store' / 'same.txt').read_text() == 'first'
    assert (tmp_path / 'store' / 'same-1.txt').read_text() == 'second'


def test_hostile_names_sanitized(tmp_path):
    src = tmp_path / 'x.txt'
    src.write_text('content')
    store = tmp_path / 'store'
    ingest_file('../../etc/passwd', str(src), None, str(store))
    stored = os.listdir(store)
    assert stored == ['passwd']  # basename only, no traversal


def test_ingest_elements_combines_blocks(tmp_path):
    a = tmp_path / 'a.txt'
    a.write_text('alpha')
    b = tmp_path / 'b.txt'
    b.write_text('beta')
    block = ingest_elements(
        [FakeElement('a.txt', str(a)), FakeElement('b.txt', str(b))],
        str(tmp_path / 'store'))
    assert 'alpha' in block and 'beta' in block
    assert block.startswith('[Files attached by the user]')
    assert ingest_elements([], str(tmp_path / 'store')) is None
