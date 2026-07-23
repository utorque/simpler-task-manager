"""Slash commands: inject workspace entities into the conversation context.

Each handler returns a markdown CONTEXT BLOCK (sent into the thread as a
system message by chainlit_app.py, so it persists in history and survives
thread resume) — or a user-facing error string. The model then answers the
user's message with that context in front of it.

Commands (registered with the Chainlit composer in chainlit_app.py):
  /task <id or search> [question]   one task, full detail (+ linked note)
  /note <id or search> [question]   one note, full content
  /tasks                            the current board (space-filtered)
  /notes                            the notes list (space-filtered)
"""

from chat import simpler_client, skills, workspace
from chat.simpler_client import SimplerAPIError

COMMANDS = [
    {'id': 'task', 'icon': 'square-check',
     'description': 'Add a task (and its linked note) to the context — id or search'},
    {'id': 'note', 'icon': 'notebook-text',
     'description': 'Add a note to the context — id or search'},
    {'id': 'tasks', 'icon': 'kanban',
     'description': 'Add the current task board to the context'},
    {'id': 'notes', 'icon': 'files',
     'description': 'Add the list of notes to the context'},
    {'id': 'skill', 'icon': 'graduation-cap',
     'description': 'Load a skill (reusable instructions) into the conversation'},
]

# The subset that still makes sense with the workspace switched off (chat-bar
# Context picker on *Generic*): skills are domain-agnostic, the injectors are
# not. Kept as a filter over COMMANDS so a new command can't silently miss it.
GENERIC_COMMAND_IDS = {'skill'}
GENERIC_COMMANDS = [c for c in COMMANDS if c['id'] in GENERIC_COMMAND_IDS]
WORKSPACE_COMMAND_IDS = {c['id'] for c in COMMANDS
                         if c['id'] not in GENERIC_COMMAND_IDS}


async def task_context_block(task: dict) -> str:
    """Format one task, fetching its linked note (house rule: an injected
    task always brings its note along)."""
    note = None
    if task.get('note_id'):
        try:
            note = await simpler_client.get_note(task['note_id'])
        except SimplerAPIError:
            note = None
    return workspace.format_task(task, note)


def _ambiguous(kind: str, query: str, lines: list[str]) -> str:
    listing = '\n'.join(lines)
    return (f"The user's reference “{query}” matched several {kind}s — ask "
            f"which one they mean:\n{listing}")


async def _handle_task(query: str, space_ids) -> str:
    tasks = await simpler_client.list_tasks(include_completed=True)
    matches = workspace.resolve_ref(query, tasks)
    if len(matches) == 1:
        return await task_context_block(matches[0])
    open_tasks = [t for t in tasks if t.get('status') != 'done']
    if not query.strip():
        return ('The user used /task without a reference. Open tasks they '
                'can pick from:\n' + workspace.format_task_board(open_tasks))
    if not matches:
        return (f"No task matched “{query}”. Tell the user, and offer the "
                'open tasks:\n' + workspace.format_task_board(open_tasks))
    return _ambiguous('task', query, [workspace.task_line(t) for t in matches])


async def _handle_note(query: str, space_ids) -> str:
    notes = await simpler_client.list_notes()
    matches = workspace.resolve_ref(query, notes)
    if len(matches) == 1:
        full = await simpler_client.get_note(matches[0]['id'])
        return workspace.format_note(full)
    if not query.strip():
        return ('The user used /note without a reference. Notes they can '
                'pick from:\n' + workspace.format_notes_list(notes))
    if not matches:
        return (f"No note matched “{query}”. Tell the user, and offer the "
                'existing notes:\n' + workspace.format_notes_list(notes))
    return _ambiguous('note', query, [workspace.note_line(n) for n in matches])


async def _handle_tasks(query: str, space_ids) -> str:
    tasks = await simpler_client.list_tasks(space_ids=space_ids)
    scope = 'the selected spaces' if space_ids is not None else 'all spaces'
    return (f"Current task board ({scope}):\n"
            + workspace.format_task_board(tasks))


async def _handle_notes(query: str, space_ids) -> str:
    notes = await simpler_client.list_notes(space_ids=space_ids)
    scope = 'the selected spaces' if space_ids is not None else 'all spaces'
    return (f"Notes in {scope} (use /note <id> for full content):\n"
            + workspace.format_notes_list(notes))


async def _handle_skill(query: str, space_ids) -> str:
    available = skills.list_skills()
    if not query.strip():
        if not available:
            return ('No skills are installed (instance/assistant/skills/ '
                    'or the bundled chat/skills/).')
        listing = '\n'.join(f"- **{s['name']}** — {s['description']}" for s in available)
        return ('The user used /skill without a name. Installed skills:\n'
                f'{listing}\nAsk which one to load.')
    loaded = skills.load_skill(query)
    # load_skill's unknown-name error is already model-readable; drop the
    # tool-protocol prefix in the command path.
    return loaded.removeprefix('TOOL ERROR: ')


_HANDLERS = {
    'task': _handle_task,
    'note': _handle_note,
    'tasks': _handle_tasks,
    'notes': _handle_notes,
    'skill': _handle_skill,
}


def is_known(command) -> bool:
    return command in _HANDLERS


async def handle_command(command: str, content: str,
                         space_ids: list[int] | None) -> tuple[str | None, str | None]:
    """Run a slash command. Returns (context_block, error): exactly one is
    set. The context block is model-facing; the error is user-facing."""
    handler = _HANDLERS.get(command)
    if handler is None:
        return None, f'Unknown command: /{command}'
    try:
        block = await handler((content or '').strip(), space_ids)
    except SimplerAPIError as e:
        return None, f'⚠️ {e}'
    header = '[Workspace context injected via /' + command + ']\n\n'
    return header + block, None


# ===== Starters ===============================================================

# The one starter on the assistant's welcome screen. Clicking it pulls in
# whatever the user staged from the board/notes with the pin (robot) buttons.
# The staged set lives in the browser (localStorage), so the bridge fills it in
# on click — this label is matched VERBATIM by chat/public/simpler-bridge.js, so
# keep the two in sync.
PIN_STARTER_LABEL = '📌 Work on my pinned tasks'


def build_starters(doing_tasks: list[dict] | None = None,
                   limit: int = 6) -> list[dict]:
    """The assistant's starters — just one now: pull the user's pinned
    tasks/notes into the conversation. (`doing_tasks`/`limit` are accepted for
    call-site compatibility but ignored; starters no longer mirror the board.)
    The label opens with an emoji char (always renders — no icon-font
    dependency, so no 'icon' field).

    Clicking it does NOT auto-send a model message: the bridge
    (chat/public/simpler-bridge.js) intercepts the click, reads the staged set
    and hands it to on_pin_refs, which injects each item and seeds the composer.
    'prefill' is only the graceful-degradation seed used if the bridge is
    absent (the seed lives in 'prefill', never 'message')."""
    return [
        {
            'label': PIN_STARTER_LABEL,
            'prefill': "Let's work on my pinned tasks.",
            'command': None,
        },
    ]


def starter_by_label(label: str, starters: list[dict]):
    """The starter spec whose label matches the clicked button's text
    (whitespace-tolerant — the bridge reads DOM textContent), or None."""
    needle = (label or '').strip()
    return next((s for s in starters if s['label'].strip() == needle), None)
