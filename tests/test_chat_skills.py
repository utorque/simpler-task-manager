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
    assert [s['name'] for s in toolbox.specs()] == ['use_skill']

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
