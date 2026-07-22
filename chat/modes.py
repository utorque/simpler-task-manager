"""Chat-bar Mode pickers (UI-agnostic option builders + per-message reads).

Modes are Chainlit's multi-category chat-bar pickers. This module builds the
option dicts and reads selections off incoming messages without importing
Chainlit, so the logic stays plain-pytest testable; chainlit_app.py converts
the dicts to cl.Mode/cl.ModeOption at the wire.
"""

MODEL_MODE_ID = 'model'


def build_model_mode_options(models: list[str]) -> list[dict]:
    """One ModeOption-shaped dict per configured model; the first is the
    default. All get the same lucide icon for now (per-model icons are a
    settings-panel follow-up)."""
    return [
        {
            'id': model,
            'name': model,
            'description': 'Answer with this model via the configured provider.',
            'icon': 'cpu',
            'default': index == 0,
        }
        for index, model in enumerate(models)
    ]


def current_model_from_modes(modes: dict | None, default: str) -> str:
    """The model selected in the chat bar for this message, else the default."""
    if not modes:
        return default
    return modes.get(MODEL_MODE_ID) or default


REASONING_MODE_ID = 'reasoning'


def build_reasoning_mode_options(levels: list[str]) -> list[dict]:
    """One ModeOption-shaped dict per reasoning level; 'medium' is the
    default when present, else the first level."""
    default_id = 'medium' if 'medium' in levels else (levels[0] if levels else None)
    return [
        {
            'id': level,
            'name': level.capitalize(),
            'description': f'{level.capitalize()} reasoning effort '
                           '(ignored by models without the parameter).',
            'icon': 'brain',
            'default': level == default_id,
        }
        for level in levels
    ]


def current_reasoning_from_modes(modes: dict | None, default: str) -> str:
    """The reasoning level selected for this message, else the default."""
    if not modes:
        return default
    return modes.get(REASONING_MODE_ID) or default


CONTEXT_MODE_ID = 'context'
CONTEXT_SIMPLER = 'simpler'
CONTEXT_GENERIC = 'generic'


def build_context_mode_options() -> list[dict]:
    """The Simpler-context switch: 'Simpler' (default) wires the workspace in
    — sidecar tools, spaces guidance, the workspace half of the system prompt,
    the workspace slash commands. 'Generic' strips all of it for a plain chat
    that doesn't pay those tokens; the general tools (sandbox, skills, files,
    web search) stay in both."""
    return [
        {
            'id': CONTEXT_SIMPLER,
            'name': 'Simpler',
            'description': 'Full workspace context: tasks, notes, spaces and '
                           'their tools.',
            'icon': 'puzzle',
            'default': True,
        },
        {
            'id': CONTEXT_GENERIC,
            'name': 'Generic',
            'description': 'Plain chat — no workspace tools, spaces or prompt '
                           'sections. Sandbox, skills and files stay.',
            'icon': 'message-circle',
            'default': False,
        },
    ]


def simpler_context_enabled(modes: dict | None) -> bool:
    """Whether this message runs with the Simpler workspace wired in.
    Anything but an explicit 'generic' means yes — an unset/unknown value
    (pre-Modes threads, older clients) keeps the historical behavior."""
    if not modes:
        return True
    return modes.get(CONTEXT_MODE_ID) != CONTEXT_GENERIC
