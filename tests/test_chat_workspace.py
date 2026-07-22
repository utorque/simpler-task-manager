"""chat/workspace.py — pure context formatting + reference resolution."""

from chat.workspace import (
    format_note,
    format_spaces_guidance,
    format_task,
    format_task_board,
    parse_leading_id,
    resolve_ref,
    task_line,
)


def test_parse_leading_id():
    assert parse_leading_id('#12 rest of text') == (12, 'rest of text')
    assert parse_leading_id('12 — let\'s work on this.') == (12, 'let\'s work on this.')
    assert parse_leading_id('12') == (12, '')
    assert parse_leading_id('report task') == (None, 'report task')
    assert parse_leading_id('') == (None, '')
    assert parse_leading_id(None) == (None, '')


TASKS = [
    {'id': 1, 'title': 'Write report', 'status': 'doing'},
    {'id': 2, 'title': 'Report bug upstream', 'status': 'todo'},
    {'id': 12, 'title': 'Buy milk', 'status': 'todo'},
]


def test_resolve_ref_by_id():
    assert resolve_ref('12', TASKS) == [TASKS[2]]
    assert resolve_ref('#12', TASKS) == [TASKS[2]]


def test_resolve_ref_by_title_substring():
    assert resolve_ref('milk', TASKS) == [TASKS[2]]
    matches = resolve_ref('report', TASKS)
    assert {t['id'] for t in matches} == {1, 2}


def test_resolve_ref_no_match_or_empty():
    assert resolve_ref('nonexistent', TASKS) == []
    assert resolve_ref('', TASKS) == []
    # An id that doesn't exist falls back to title search ('99' not in titles).
    assert resolve_ref('99', TASKS) == []


def test_format_task_includes_linked_note_content():
    task = {'id': 3, 'title': 'From note', 'status': 'todo', 'priority': 5,
            'note_id': 7, 'note_title': 'origin',
            'subtasks': [{'title': 'step 1', 'done': True},
                         {'title': 'step 2', 'done': False}]}
    note = {'id': 7, 'title': 'origin', 'content_markdown': 'the note body'}
    block = format_task(task, note)
    assert 'Task #3: From note' in block
    assert '- [x] step 1' in block and '- [ ] step 2' in block
    assert 'Note #7: origin' in block
    assert 'the note body' in block


def test_format_task_without_note_flags_unavailable_content():
    task = {'id': 3, 'title': 'From note', 'status': 'todo', 'note_id': 7}
    block = format_task(task, None)
    assert 'note #7' in block and 'unavailable' in block


def test_task_line_mentions_linked_note():
    line = task_line({'id': 4, 'title': 'T', 'status': 'todo',
                      'note_id': 9, 'note_title': 'N'})
    assert '#4' in line and 'note #9' in line


def test_format_task_board_groups_by_status():
    board = format_task_board([
        {'id': 1, 'title': 'a', 'status': 'todo'},
        {'id': 2, 'title': 'b', 'status': 'doing'},
    ])
    assert board.index('**doing**') < board.index('**todo**')
    assert format_task_board([]) == '*The board is empty.*'


def test_format_note_handles_empty_content():
    assert 'empty note' in format_note({'id': 1, 'title': 't', 'content_markdown': ''})


SPACES = [
    {'id': 1, 'name': 'work', 'description': 'day job', 'context_markdown': 'Be formal.'},
    {'id': 2, 'name': 'study', 'description': '', 'context_markdown': ''},
]


def test_spaces_guidance_all_spaces():
    text = format_spaces_guidance(SPACES, None)
    assert 'work' in text and 'study' in text and 'Be formal.' in text


def test_spaces_guidance_filtered():
    text = format_spaces_guidance(SPACES, [1])
    assert 'Space: work' in text
    assert 'Space: study' not in text
    assert 'filtered out: study' in text
