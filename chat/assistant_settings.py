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
import re

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


def read_system_prompt_source() -> str:
    """The prompt file VERBATIM, conditional markers included — what the
    settings-panel editor loads and writes back. Never feed this to the
    model; go through `load_system_prompt` so the markers get resolved."""
    try:
        with open(system_prompt_path(), encoding='utf-8') as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ('You are the built-in assistant of Simpler, a personal '
                'task/notes workspace.')


def load_system_prompt(simpler: bool = True) -> str:
    """The base system prompt as the model should receive it — instance
    override when present, else the shipped default. Called PER MESSAGE
    (never cached module-globally) so in-app edits take effect on the next
    turn.

    `simpler=False` (chat-bar Context picker on *Generic*) drops the
    workspace-only sections — see `select_prompt_sections`."""
    return select_prompt_sections(read_system_prompt_source(), simpler)


# --- Conditional prompt sections ---------------------------------------------
# One editable prompt file, two audiences. Blocks fenced by HTML comments are
# kept or dropped depending on the Context mode, so the user still edits ONE
# system.md in the settings panel (no second file, no second override path).

SIMPLER_BLOCK = ('simpler:start', 'simpler:end')
GENERIC_BLOCK = ('generic:start', 'generic:end')


def _strip_blocks(text: str, markers: tuple[str, str]) -> str:
    """Drop every `<!-- start -->` … `<!-- end -->` block, marker lines
    included. An unclosed opener drops the rest of the file (fail closed:
    better a short prompt than a leaked section)."""
    open_marker, close_marker = markers
    kept, skipping = [], False
    for line in text.splitlines():
        probe = line.strip()
        if not skipping and probe.startswith('<!--') and open_marker in probe:
            skipping = True
            continue
        if skipping:
            if probe.endswith('-->') and close_marker in probe:
                skipping = False
            continue
        kept.append(line)
    return '\n'.join(kept)


def select_prompt_sections(text: str, simpler: bool = True) -> str:
    """Resolve the conditional blocks for one Context mode, then collapse the
    blank runs the removals leave behind. A prompt with no markers (any older
    instance override) comes back unchanged in Simpler mode.

    Surviving HTML comments are dropped too — they are notes to whoever edits
    the prompt (starting with the marker legend at the top of system.md), and
    the model should not pay for them."""
    text = _strip_blocks(text, GENERIC_BLOCK if simpler else SIMPLER_BLOCK)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    lines, out = text.splitlines(), []
    for line in lines:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return '\n'.join(out).strip()


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


def available_models() -> list[str]:
    """The model-picker list: instance models.json when non-empty, else the
    CHAT_MODELS/AI_MODEL env chain (settings.chat_models()). First entry is
    the default."""
    return read_models() or settings.chat_models()


# ===== Reasoning levels (Bundle B) ============================================

DEFAULT_REASONING_LEVELS = ['low', 'medium', 'high']


def reasoning_json_path() -> str:
    return os.path.join(instance_dir(), 'reasoning.json')


def read_reasoning_levels() -> list[str]:
    try:
        with open(reasoning_json_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [str(level).strip() for level in data if str(level).strip()]


def write_reasoning_levels(levels: list[str]):
    with open(reasoning_json_path(), 'w', encoding='utf-8') as f:
        json.dump(list(levels), f, indent=2)


def available_reasoning_levels() -> list[str]:
    return read_reasoning_levels() or list(DEFAULT_REASONING_LEVELS)


# ===== Skills dirs (Bundle B) =================================================

def instance_skills_dir() -> str:
    """User-authored skills (read+write); shadows bundled names."""
    path = os.path.join(instance_dir(), 'skills')
    os.makedirs(path, exist_ok=True)
    return path


def bundled_skills_dir() -> str:
    """The shipped read-only skill set (git-tracked)."""
    return os.path.join(settings.CHAT_DIR, 'skills')
