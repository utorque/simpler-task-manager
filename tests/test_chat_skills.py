"""chat/skills.py — skill packages: listing, loading, prompt section."""

import os

from chat import skills
from chat.toolbox import Toolbox


def make_skill(root, name, body, front_matter=True, extra_files=()):
    directory = root / name
    directory.mkdir(parents=True)
    text = body
    if front_matter:
        text = f'---\nname: {name}\ndescription: does {name} things\n---\n{body}'
    (directory / 'SKILL.md').write_text(text)
    for extra in extra_files:
        (directory / extra).write_text('helper')
    return directory


def test_list_skills_reads_front_matter(tmp_path):
    make_skill(tmp_path, 'alpha', '# Alpha\ninstructions')
    make_skill(tmp_path, 'beta', 'First paragraph is the description.\n\nMore.',
               front_matter=False)
    (tmp_path / 'not-a-skill').mkdir()  # no SKILL.md -> ignored

    listed = skills.list_skills(str(tmp_path))
    assert [s['name'] for s in listed] == ['alpha', 'beta']
    assert listed[0]['description'] == 'does alpha things'
    assert listed[1]['description'] == 'First paragraph is the description.'


def test_load_skill_strips_front_matter_and_lists_files(tmp_path):
    make_skill(tmp_path, 'alpha', '# Alpha\nDo the alpha dance.',
               extra_files=('helper.py',))
    loaded = skills.load_skill('alpha', str(tmp_path))
    assert loaded.startswith('[Skill loaded: alpha]')
    assert 'Do the alpha dance.' in loaded
    assert '---' not in loaded
    assert 'helper.py' in loaded


def test_load_skill_unknown_lists_available(tmp_path):
    make_skill(tmp_path, 'alpha', 'x')
    message = skills.load_skill('nope', str(tmp_path))
    assert message.startswith('TOOL ERROR')
    assert 'alpha' in message


def test_load_skill_case_insensitive(tmp_path):
    make_skill(tmp_path, 'Alpha', 'body')
    assert 'body' in skills.load_skill('alpha', str(tmp_path))


def test_prompt_section(tmp_path):
    assert skills.prompt_section(str(tmp_path / 'missing')) is None
    make_skill(tmp_path, 'alpha', 'x')
    section = skills.prompt_section(str(tmp_path))
    assert section.startswith('## Skills')
    assert 'alpha' in section


def test_use_skill_tool_registration(tmp_path):
    make_skill(tmp_path, 'alpha', 'the alpha instructions')
    toolbox = Toolbox()
    skills.register(toolbox, str(tmp_path))
    assert 'use_skill' in [s['name'] for s in toolbox.specs()]

    import asyncio
    output = asyncio.run(toolbox.execute('use_skill', {'name': 'alpha'}))
    assert 'the alpha instructions' in output


def test_shipped_skills_are_valid():
    shipped = skills.list_skills()
    names = {s['name'] for s in shipped}
    assert {'weekly-review', 'braindump'} <= names
    assert all(s['description'] for s in shipped)
    loaded = skills.load_skill('weekly-review')
    assert 'get_workspace_summary' in loaded


# ===== Issue 003.06: skills authoring (instance dir + agent tools) ===========

import os

import pytest

from chat import settings as chat_settings


@pytest.fixture
def instance_root(tmp_path, monkeypatch):
    """Point the instance skills dir at a temp path; the bundled dir stays
    the real chat/skills/ (read-only shipped set)."""
    monkeypatch.delenv('CHAT_SKILLS_DIR', raising=False)
    root = tmp_path / 'instance'
    monkeypatch.setattr(chat_settings, 'INSTANCE_DIR', str(root))
    return root


def test_create_skill_writes_instance_dir(instance_root):
    message = skills.create_skill(name='myflow', description='my flow',
                                  body='# Steps\nDo the flow.')
    assert not message.startswith('TOOL ERROR')
    skill_md = instance_root / 'assistant' / 'skills' / 'myflow' / 'SKILL.md'
    assert skill_md.is_file()
    text = skill_md.read_text()
    assert 'name: myflow' in text and 'description: my flow' in text
    assert 'Do the flow.' in text


def test_create_skill_bundles_extra_files(instance_root):
    skills.create_skill(name='withfiles', description='d', body='b',
                        files={'helper.py': 'print(1)'})
    helper = instance_root / 'assistant' / 'skills' / 'withfiles' / 'helper.py'
    assert helper.read_text() == 'print(1)'


def test_create_skill_rejects_collision(instance_root):
    skills.create_skill(name='myflow', description='d', body='b')
    message = skills.create_skill(name='myflow', description='d', body='b2')
    assert message.startswith('TOOL ERROR')
    # No overwrite happened.
    skill_md = instance_root / 'assistant' / 'skills' / 'myflow' / 'SKILL.md'
    assert 'b2' not in skill_md.read_text()


def test_create_skill_rejects_bundled_name_collision(instance_root):
    message = skills.create_skill(name='braindump', description='d', body='b')
    assert message.startswith('TOOL ERROR')
    assert 'braindump' in message


def test_create_skill_rejects_bad_names(instance_root):
    for bad in ('../evil', 'a/b', '', '.hidden', 'no\0null'):
        assert skills.create_skill(name=bad, description='d',
                                   body='b').startswith('TOOL ERROR')


def test_list_skills_merges_instance_and_bundled(instance_root):
    skills.create_skill(name='myflow', description='mine', body='b')
    listed = skills.list_skills()
    by_name = {s['name']: s for s in listed}
    assert by_name['myflow']['source'] == 'instance'
    assert by_name['braindump']['source'] == 'bundled'
    # Instance skills come first.
    assert listed[0]['source'] == 'instance'
    # Name shadowing: an instance fork hides the bundled one (no duplicates).
    skills.update_skill('braindump', body='forked body')
    listed = skills.list_skills()
    assert [s['name'] for s in listed].count('braindump') == 1
    assert next(s for s in listed if s['name'] == 'braindump')['source'] == 'instance'


def test_delete_skill_instance_only(instance_root):
    skills.create_skill(name='myflow', description='d', body='b')
    assert not skills.delete_skill('myflow').startswith('TOOL ERROR')
    assert not (instance_root / 'assistant' / 'skills' / 'myflow').exists()
    assert skills.delete_skill('braindump').startswith('TOOL ERROR')
    assert skills.delete_skill('missing').startswith('TOOL ERROR')


def test_update_skill_body(instance_root):
    skills.create_skill(name='myflow', description='keep me', body='v1')
    message = skills.update_skill('myflow', body='v2')
    assert not message.startswith('TOOL ERROR')
    text = (instance_root / 'assistant' / 'skills' / 'myflow' / 'SKILL.md').read_text()
    assert 'v2' in text and 'v1' not in text
    assert 'description: keep me' in text  # front matter preserved


def test_update_bundled_skill_copies_to_instance(instance_root):
    """Copy-to-instance-then-edit: editing a bundled skill forks it; the
    shipped chat/skills/ is never mutated."""
    shipped_md = os.path.join(skills.bundled_skills_dir(), 'braindump', 'SKILL.md')
    shipped_before = open(shipped_md).read()

    message = skills.update_skill('braindump', body='my custom braindump')
    assert not message.startswith('TOOL ERROR')
    fork = instance_root / 'assistant' / 'skills' / 'braindump' / 'SKILL.md'
    assert 'my custom braindump' in fork.read_text()
    assert open(shipped_md).read() == shipped_before

    assert skills.update_skill('missing', body='x').startswith('TOOL ERROR')


def test_load_skill_resolves_instance_fork_first(instance_root):
    skills.update_skill('braindump', body='forked instructions')
    loaded = skills.load_skill('braindump')
    assert 'forked instructions' in loaded


def test_authoring_tools_registered(instance_root):
    toolbox = Toolbox()
    skills.register(toolbox)
    names = [s['name'] for s in toolbox.specs()]
    assert {'use_skill', 'create_skill', 'update_skill', 'delete_skill'} <= set(names)

    import asyncio
    output = asyncio.run(toolbox.execute('create_skill', {
        'name': 'viatool', 'description': 'd', 'body': 'the body'}))
    assert not output.startswith('TOOL ERROR')
    assert 'viatool' in [s['name'] for s in skills.list_skills()]
