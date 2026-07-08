"""Skills: reusable instruction packages the model loads on demand.

A skill is a directory under chat/skills/ (or CHAT_SKILLS_DIR) containing a
SKILL.md — instructions written for the MODEL, optionally opening with a
`---` front-matter block (`name:` / `description:`). The system prompt
advertises name+description of every skill; the model (or the user, via
/skill) pulls the full instructions into the conversation only when needed,
keeping the base prompt small. Extra files in a skill directory are listed
so file/sandbox tools can use them.
"""

import os
import re

from chat import settings

USE_SKILL_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string', 'description': 'The skill name, as listed'},
    },
    'required': ['name'],
}


def skills_dir() -> str:
    return os.getenv('CHAT_SKILLS_DIR') or os.path.join(settings.CHAT_DIR, 'skills')


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r'\A---\s*\n(.*?)\n---\s*\n?(.*)\Z', text, re.DOTALL)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(':')
        if sep:
            meta[key.strip().lower()] = value.strip()
    return meta, match.group(2)


def list_skills(directory: str | None = None) -> list[dict]:
    """[{'name', 'description', 'dir'}] for every valid skill package."""
    directory = directory or skills_dir()
    found = []
    if not os.path.isdir(directory):
        return found
    for entry in sorted(os.listdir(directory)):
        skill_md = os.path.join(directory, entry, 'SKILL.md')
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, encoding='utf-8') as f:
                meta, body = _parse_front_matter(f.read())
        except OSError:
            continue
        description = meta.get('description') or next(
            (line.strip() for line in body.splitlines()
             if line.strip() and not line.startswith('#')), '')
        found.append({
            'name': meta.get('name') or entry,
            'description': description,
            'dir': os.path.join(directory, entry),
        })
    return found


def load_skill(name: str, directory: str | None = None) -> str:
    """Full SKILL.md body (front matter stripped) + a listing of the skill's
    bundled files. Unknown name -> helpful error listing what exists."""
    skills = list_skills(directory)
    match = next((s for s in skills if s['name'].lower() == (name or '').lower()), None)
    if match is None:
        names = ', '.join(s['name'] for s in skills) or '(none installed)'
        return f'TOOL ERROR: no skill named {name!r}. Available skills: {names}'
    with open(os.path.join(match['dir'], 'SKILL.md'), encoding='utf-8') as f:
        _, body = _parse_front_matter(f.read())
    extras = [entry for entry in sorted(os.listdir(match['dir']))
              if entry != 'SKILL.md']
    listing = ''
    if extras:
        files = '\n'.join(f"- `{os.path.join(match['dir'], entry)}`" for entry in extras)
        listing = f'\n\nBundled files (readable with file/sandbox tools):\n{files}'
    return (f"[Skill loaded: {match['name']}]\n\n{body.strip()}{listing}")


def prompt_section(directory: str | None = None) -> str | None:
    """The '## Skills' block for the system prompt, or None when empty."""
    skills = list_skills(directory)
    if not skills:
        return None
    lines = ['## Skills',
             'Load a skill with the use_skill tool when its situation comes '
             'up; then follow its instructions:']
    lines += [f"- **{s['name']}** — {s['description']}" for s in skills]
    return '\n'.join(lines)


def register(toolbox, directory: str | None = None):
    def use_skill(name: str) -> str:
        return load_skill(name, directory)
    toolbox.add_native(
        'use_skill',
        'Load a skill (a reusable instruction package) by name and follow it. '
        'Available skills are listed in the system prompt.',
        USE_SKILL_SCHEMA, use_skill)
