"""System-prompt assembly for AI calls (deduplicated from 3 route sites).

The LLM needs the Space list (id, name, description) appended to the base
task-parsing prompt so it can pick a `space_id`. Both the task-parse route and
the notes promote-to-task route build the exact same context through here.
"""

from flask import current_app

from models import Space


def build_task_parse_prompt(space_hint=None):
    """Base SYSTEM_PROMPT + available-spaces context (+ optional space hint)."""
    spaces = Space.query.all()
    spaces_info = "\n".join(
        f"- ID: {space.id}, Name: {space.name}, Description: {space.description}"
        for space in spaces
    )
    system_prompt = current_app.config['SYSTEM_PROMPT'] + "\n\nAvailable spaces:\n" + spaces_info

    if space_hint:
        system_prompt += (
            f"\n\nIMPORTANT: This task should be assigned to the '{space_hint}' "
            "space unless the user explicitly specifies a different space."
        )
    return system_prompt
