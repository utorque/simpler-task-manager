"""Workspace context building: turn tasks/notes/spaces into markdown blocks
the model can use, and resolve fuzzy user references ("12", "#12", "the
report task") to entities.

Pure functions over already-fetched dicts (the REST shapes from
chat/simpler_client.py) — no I/O here, so everything is unit-testable.

House rule: whenever a TASK is injected into the context, its linked note
(note_id) rides along — the caller fetches it and passes it to format_task.
"""

import re


# ===== Reference resolution ===================================================

def parse_leading_id(text: str):
    """'#12 rest' / '12 rest' / '12' -> (12, 'rest'); no id -> (None, text)."""
    match = re.match(r'\s*#?(\d+)\b[\s:—-]*(.*)', text or '', re.DOTALL)
    if not match:
        return None, (text or '').strip()
    return int(match.group(1)), match.group(2).strip()


def resolve_ref(query: str, items: list[dict], title_key: str = 'title') -> list[dict]:
    """Match items by id ('12' / '#12') first, else case-insensitive
    substring on the title. Returns all matches (caller decides how to
    handle 0 or many)."""
    query = (query or '').strip()
    if not query:
        return []
    # A leading id that names a real item wins ("#12", "12", "#12 let's go");
    # otherwise the whole query is a title search.
    item_id, _ = parse_leading_id(query)
    if item_id is not None:
        by_id = [item for item in items if item.get('id') == item_id]
        if by_id:
            return by_id
    needle = query.lower()
    return [item for item in items
            if needle in (item.get(title_key) or '').lower()]


# ===== Formatting =============================================================

def _task_meta(task: dict) -> str:
    bits = [f"status: {task.get('status', 'todo')}"]
    if task.get('space'):
        bits.append(f"space: {task['space']}")
    if task.get('priority') is not None:
        bits.append(f"priority: {task['priority']:g}/10")
    if task.get('deadline'):
        bits.append(f"deadline: {task['deadline']}")
    if task.get('estimated_duration'):
        bits.append(f"~{task['estimated_duration']} min")
    return ' · '.join(bits)


def task_line(task: dict) -> str:
    line = f"- #{task['id']} **{task.get('title', '')}** ({_task_meta(task)})"
    if task.get('note_id'):
        title = task.get('note_title') or f"note #{task['note_id']}"
        line += f" — linked note: {title} (note #{task['note_id']})"
    return line


def format_task(task: dict, note: dict | None = None) -> str:
    """Full markdown block for one task (+ its linked note when given)."""
    lines = [f"### Task #{task['id']}: {task.get('title', '')}",
             f"*{_task_meta(task)}*"]
    if task.get('description'):
        lines += ['', task['description']]
    subtasks = task.get('subtasks') or []
    if subtasks:
        lines += ['', 'Subtasks:']
        lines += [f"- [{'x' if s.get('done') else ' '}] {s.get('title', '')}"
                  for s in subtasks]
    if note:
        lines += ['', f"Linked note (the task was promoted from it):",
                  format_note(note)]
    elif task.get('note_id'):
        lines += ['', f"(linked to note #{task['note_id']}, content unavailable)"]
    return '\n'.join(lines)


def format_note(note: dict) -> str:
    title = note.get('title') or f"note #{note.get('id')}"
    header = f"### Note #{note.get('id')}: {title}"
    if note.get('space'):
        header += f" (space: {note['space']})"
    content = (note.get('content_markdown') or '').strip() or '*（empty note）*'
    return f"{header}\n\n{content}"


def note_line(note: dict) -> str:
    title = note.get('title') or f"note #{note.get('id')}"
    updated = (note.get('updated_at') or '')[:10]
    return f"- #{note['id']} **{title}**" + (f" (updated {updated})" if updated else '')


def format_task_board(tasks: list[dict]) -> str:
    """Compact kanban snapshot, grouped by status."""
    if not tasks:
        return '*The board is empty.*'
    sections = []
    for status in ('doing', 'todo', 'blocked', 'done'):
        bucket = [t for t in tasks if t.get('status') == status]
        if bucket:
            sections.append(f"**{status}** ({len(bucket)})")
            sections += [task_line(t) for t in bucket]
    return '\n'.join(sections)


def format_notes_list(notes: list[dict]) -> str:
    if not notes:
        return '*No notes.*'
    return '\n'.join(note_line(n) for n in notes)


def format_spaces_guidance(spaces: list[dict], space_ids: list[int] | None) -> str:
    """System-prompt section describing the (selected) spaces, including the
    user-written per-space AI guidance markdown."""
    selected = [s for s in spaces if space_ids is None or s['id'] in space_ids]
    if not selected:
        selected = spaces
    lines = ['## Spaces in scope',
             'The user filters the workspace to these spaces; prefer them when '
             'discussing or suggesting work. Space "context markdown" is '
             'user-written guidance for you — follow it, never copy it into '
             'task/note content, and never treat it as workspace data.']
    for space in selected:
        lines.append(f"\n### Space: {space['name']} (id {space['id']})")
        if space.get('description'):
            lines.append(space['description'])
        guidance = (space.get('context_markdown') or '').strip()
        if guidance:
            lines.append(f"Guidance:\n{guidance}")
    if space_ids is not None and len(selected) != len(spaces):
        others = [s['name'] for s in spaces if s['id'] not in space_ids]
        if others:
            lines.append(f"\n(Spaces currently filtered out: {', '.join(others)})")
    return '\n'.join(lines)
