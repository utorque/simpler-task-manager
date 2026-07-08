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
