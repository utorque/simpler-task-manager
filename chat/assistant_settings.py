"""Per-instance assistant storage under instance/assistant/.

Home of everything the user customizes about the assistant from the app
(editable system prompt override, model-picker list, instance-scoped
skills). Files-on-disk only — gitignored (the instance/ rule), so
customizations survive `git pull` upgrades and there is no DB coupling.

Pure stdlib + chat.settings: importable by Flask route code and tests
without Chainlit's runtime.
"""

import json
import os

from chat import settings


def instance_dir() -> str:
    path = os.path.join(settings.INSTANCE_DIR, 'assistant')
    os.makedirs(path, exist_ok=True)
    return path


# ===== System prompt (Bundle B) ===============================================

def shipped_system_prompt_path() -> str:
    return os.path.join(settings.CHAT_DIR, 'prompts', 'system.md')


def system_prompt_override_path() -> str:
    return os.path.join(instance_dir(), 'system.md')


def system_prompt_path() -> str:
    """The file the base system prompt is read from: the instance override
    when the user has edited it in-app, else the shipped default."""
    override = system_prompt_override_path()
    if os.path.isfile(override):
        return override
    return shipped_system_prompt_path()


def reset_system_prompt():
    """Delete the instance override — 'reset to shipped'."""
    try:
        os.remove(system_prompt_override_path())
    except FileNotFoundError:
        pass


def load_system_prompt() -> str:
    """The base system prompt text — instance override when present, else
    the shipped default. Called PER MESSAGE (never cached module-globally)
    so in-app edits take effect on the next turn."""
    try:
        with open(system_prompt_path(), encoding='utf-8') as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ('You are the built-in assistant of Simpler, a personal '
                'task/notes workspace.')


# ===== Model list (Bundle A) ==================================================

def models_json_path() -> str:
    return os.path.join(instance_dir(), 'models.json')


def read_models() -> list[str]:
    """The user-managed model list; [] when absent/empty/corrupt (callers
    fall back to the CHAT_MODELS/AI_MODEL env chain)."""
    try:
        with open(models_json_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [str(m).strip() for m in data if str(m).strip()]


def write_models(models: list[str]):
    with open(models_json_path(), 'w', encoding='utf-8') as f:
        json.dump(list(models), f, indent=2)


# ===== Skills dirs (Bundle B) =================================================

def instance_skills_dir() -> str:
    """User-authored skills (read+write); shadows bundled names."""
    path = os.path.join(instance_dir(), 'skills')
    os.makedirs(path, exist_ok=True)
    return path


def bundled_skills_dir() -> str:
    """The shipped read-only skill set (git-tracked)."""
    return os.path.join(settings.CHAT_DIR, 'skills')
