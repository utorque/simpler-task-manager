"""System-prompt assembly for AI calls (deduplicated from the route sites).

Every task-drafting prompt (quick-capture parse, note promote-to-task,
email-to-task) is assembled here from three layers:

  1. the base system prompt (the JSON formatting contract, per entry point),
  2. the Space list (id, name, description) so the LLM can pick a `space_id`,
  3. the per-space user-written context markdown, framed as GUIDANCE ONLY —
     it helps the model make good decisions (space choice, priority, deadline,
     phrasing) but must never be treated as task content or as part of the
     user's request.
"""

from flask import current_app

from models import Space


def spaces_context():
    """The 'Available spaces' block appended to every task-drafting prompt."""
    spaces = Space.query.all()
    spaces_info = "\n".join(
        f"- ID: {space.id}, Name: {space.name}, Description: {space.description}"
        for space in spaces
    )
    return "Available spaces:\n" + spaces_info


def space_guidance_block():
    """User-written per-space context, wrapped in guide-not-source framing.

    Empty string when no space has any context, so prompts without it are
    byte-identical to the pre-feature ones.
    """
    spaces = Space.query.all()
    with_context = [
        (space.name, space.context_markdown.strip())
        for space in spaces
        if space.context_markdown and space.context_markdown.strip()
    ]
    if not with_context:
        return ""

    sections = "\n\n".join(
        f"### Space: {name}\n{context}" for name, context in with_context
    )
    return (
        "\n\n--- SPACE CONTEXT (guidance only) ---\n"
        "The user wrote the following background notes about their spaces. "
        "Use them ONLY to guide your decisions: which space fits, sensible "
        "priority, deadline, duration, and wording. They are NOT part of the "
        "user's request — never copy their text into task fields and never "
        "derive tasks from them. Treat them as a guide, not a source.\n\n"
        + sections +
        "\n--- END SPACE CONTEXT ---"
    )


def build_task_parse_prompt(space_hint=None):
    """Base SYSTEM_PROMPT + spaces context + space guidance (+ optional hint)."""
    system_prompt = (
        current_app.config['SYSTEM_PROMPT']
        + "\n\n" + spaces_context()
        + space_guidance_block()
    )

    if space_hint:
        system_prompt += (
            f"\n\nIMPORTANT: This task should be assigned to the '{space_hint}' "
            "space unless the user explicitly specifies a different space."
        )
    return system_prompt


def build_email_to_task_prompt():
    """EMAIL_TO_TASK_PROMPT + spaces context + space guidance."""
    return (
        current_app.config['EMAIL_TO_TASK_PROMPT']
        + "\n\n" + spaces_context()
        + space_guidance_block()
    )
