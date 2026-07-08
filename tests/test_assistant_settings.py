"""chat/assistant_settings.py — instance/assistant/ app-data dir foundation.

All per-instance assistant storage (editable system prompt, model list,
instance-scoped skills) lives under instance/assistant/ (gitignored,
survives upgrades). This suite pins the path-resolution contract every
downstream issue (003.03–003.07) builds on.
"""

import os
import subprocess

import pytest

from chat import assistant_settings, settings


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    """Redirect the instance dir to a temp path so tests never touch the
    repo's real instance/."""
    root = tmp_path / 'instance'
    monkeypatch.setattr(settings, 'INSTANCE_DIR', str(root))
    return root


def test_instance_dir_created_on_access(instance_root):
    path = assistant_settings.instance_dir()
    assert path == str(instance_root / 'assistant')
    assert os.path.isdir(path)


def test_system_prompt_path_returns_override_when_present(instance_root):
    shipped = os.path.join(settings.CHAT_DIR, 'prompts', 'system.md')
    assert assistant_settings.system_prompt_path() == shipped

    override = instance_root / 'assistant' / 'system.md'
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text('# My custom prompt')
    assert assistant_settings.system_prompt_path() == str(override)

    assistant_settings.reset_system_prompt()
    assert not override.exists()
    assert assistant_settings.system_prompt_path() == shipped
    # Reset with no override present is a no-op, not an error.
    assistant_settings.reset_system_prompt()


def test_models_json_path(instance_root):
    path = assistant_settings.models_json_path()
    assert path == str(instance_root / 'assistant' / 'models.json')
    assert assistant_settings.read_models() == []  # absent -> [] (no crash)

    assistant_settings.write_models(['gpt-4o', 'claude-3-7-sonnet'])
    assert assistant_settings.read_models() == ['gpt-4o', 'claude-3-7-sonnet']


def test_read_models_tolerates_bad_json(instance_root):
    path = assistant_settings.models_json_path()
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{not json')
    assert assistant_settings.read_models() == []
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{"not": "a list"}')
    assert assistant_settings.read_models() == []


def test_skills_dir_instance_then_shipped(instance_root):
    instance_skills = assistant_settings.instance_skills_dir()
    assert instance_skills == str(instance_root / 'assistant' / 'skills')
    assert os.path.isdir(instance_skills)

    bundled = assistant_settings.bundled_skills_dir()
    assert bundled == os.path.join(settings.CHAT_DIR, 'skills')
    assert os.path.isdir(bundled)


def test_gitignore_entry_added():
    """instance/assistant/ must be gitignored (covered by the existing
    instance/ rule) — verified against git itself, not by string-matching
    .gitignore."""
    result = subprocess.run(
        ['git', 'check-ignore', '-q', 'instance/assistant/system.md'],
        cwd=settings.REPO_ROOT)
    assert result.returncode == 0


def test_importable_without_chainlit():
    """assistant_settings must stay pure (stdlib + chat.settings) so route
    code and tests can import it without Chainlit's runtime."""
    import inspect
    source = inspect.getsource(assistant_settings)
    assert 'chainlit' not in source
