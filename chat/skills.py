"""Skills: reusable instruction packages the model loads on demand.

A skill is a directory containing a SKILL.md — instructions written for the
MODEL, optionally opening with a `---` front-matter block (`name:` /
`description:`). The system prompt advertises name+description of every
skill; the model (or the user, via /skill) pulls the full instructions into
the conversation only when needed, keeping the base prompt small. Extra
files in a skill directory are listed so file/sandbox tools can use them.

Two roots (issue 003.06):
- instance/assistant/skills/ — user-authored, read+write (the create/
  update/delete tools and the settings panel operate here); survives
  upgrades.
- chat/skills/ — the bundled shipped set, read-only. Editing a bundled
  skill forks it: copy-to-instance-then-edit, and the instance copy shadows
  the bundled one by name from then on.
"""

import os
import re
import shutil

from chat import assistant_settings

USE_SKILL_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string', 'description': 'The skill name, as listed'},
    },
    'required': ['name'],
}

CREATE_SKILL_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string',
                 'description': 'Skill name (letters/digits/._- , no spaces)'},
        'description': {'type': 'string',
                        'description': 'One-line description shown in listings'},
        'body': {'type': 'string',
                 'description': 'The SKILL.md instructions (markdown, written '
                                'for the model to follow)'},
        'files': {'type': 'object',
                  'description': 'Optional extra text files bundled with the '
                                 'skill: {filename: content}',
                  'additionalProperties': {'type': 'string'}},
    },
    'required': ['name', 'description', 'body'],
}

UPDATE_SKILL_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string', 'description': 'The skill to update'},
        'body': {'type': 'string', 'description': 'The new SKILL.md body'},
        'description': {'type': 'string',
                        'description': 'Optional new one-line description'},
    },
    'required': ['name', 'body'],
}

DELETE_SKILL_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string', 'description': 'The skill to delete'},
    },
    'required': ['name'],
}

_NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z')


def skills_dir() -> str:
    """The writable skills root (instance dir; CHAT_SKILLS_DIR overrides)."""
    return os.getenv('CHAT_SKILLS_DIR') or assistant_settings.instance_skills_dir()


def bundled_skills_dir() -> str:
    """The shipped read-only skill set."""
    return assistant_settings.bundled_skills_dir()


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


def _list_dir(directory: str, source: str) -> list[dict]:
    """[{'name', 'description', 'dir', 'source'}] for one skills root."""
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
            'source': source,
        })
    return found


def list_skills(directory: str | None = None) -> list[dict]:
    """Every valid skill package. Default: instance skills first, then the
    bundled set, with instance winning name clashes (a fork shadows its
    bundled original). An explicit `directory` lists only that root."""
    if directory is not None:
        return _list_dir(directory, 'instance')
    instance = _list_dir(skills_dir(), 'instance')
    taken = {s['name'].lower() for s in instance}
    bundled = [s for s in _list_dir(bundled_skills_dir(), 'bundled')
               if s['name'].lower() not in taken]
    return instance + bundled


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


# ===== Authoring (instance dir only; bundled skills are read-only) ===========

def _render_skill_md(name: str, description: str, body: str) -> str:
    return f'---\nname: {name}\ndescription: {description}\n---\n{body}\n'


def _valid_name(name: str) -> bool:
    return bool(name) and bool(_NAME_RE.fullmatch(name)) and '..' not in name


def _find(name: str, source: str | None = None):
    for skill in list_skills():
        if skill['name'].lower() == (name or '').lower():
            if source is None or skill['source'] == source:
                return skill
            return None
    return None


def create_skill(name: str, description: str, body: str,
                 files: dict | None = None) -> str:
    """Write a new instance skill package. Rejects invalid names and
    collisions with existing instance OR bundled skills (no overwrite)."""
    if not _valid_name(name):
        return ('TOOL ERROR: invalid skill name — use letters/digits/._- '
                'with no spaces or path separators.')
    existing = _find(name)
    if existing is not None:
        return (f'TOOL ERROR: a skill named {name!r} already exists '
                f"({existing['source']}). Pick a different name"
                + (' or edit it with update_skill.'
                   if existing['source'] == 'instance'
                   else ' (bundled skills are read-only; update_skill forks '
                        'them to the instance dir).'))
    target = os.path.join(skills_dir(), name)
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, 'SKILL.md'), 'w', encoding='utf-8') as f:
        f.write(_render_skill_md(name, description, body))
    for filename, content in (files or {}).items():
        safe = os.path.basename(filename)
        if not safe or safe.startswith('.'):
            continue
        with open(os.path.join(target, safe), 'w', encoding='utf-8') as f:
            f.write(content)
    return f'Skill {name!r} created in the instance skills directory.'


def update_skill(name: str, body: str, description: str | None = None) -> str:
    """Rewrite an instance skill's body (front matter preserved unless a new
    description is given). Editing a BUNDLED skill forks it first
    (copy-to-instance-then-edit); the shipped set is never mutated."""
    instance = _find(name, 'instance')
    forked = ''
    if instance is None:
        bundled = _find(name, 'bundled')
        if bundled is None:
            names = ', '.join(s['name'] for s in list_skills()) or '(none)'
            return f'TOOL ERROR: no skill named {name!r}. Available: {names}'
        target = os.path.join(skills_dir(), os.path.basename(bundled['dir']))
        shutil.copytree(bundled['dir'], target)
        instance = {**bundled, 'dir': target, 'source': 'instance'}
        forked = ' (bundled skill forked to the instance dir; the shipped copy is untouched)'
    skill_md = os.path.join(instance['dir'], 'SKILL.md')
    with open(skill_md, encoding='utf-8') as f:
        meta, _ = _parse_front_matter(f.read())
    new_description = description or meta.get('description') or ''
    with open(skill_md, 'w', encoding='utf-8') as f:
        f.write(_render_skill_md(instance['name'], new_description, body))
    return f'Skill {name!r} updated{forked}.'


def delete_skill(name: str) -> str:
    """Remove an instance skill. Bundled skills are undeletable."""
    if _find(name, 'bundled') is not None:
        return (f'TOOL ERROR: {name!r} is a bundled (shipped) skill and '
                'cannot be deleted.')
    instance = _find(name, 'instance')
    if instance is None:
        return f'TOOL ERROR: no instance skill named {name!r}.'
    shutil.rmtree(instance['dir'])
    return f'Skill {name!r} deleted.'


def register(toolbox, directory: str | None = None):
    def use_skill(name: str) -> str:
        return load_skill(name, directory)
    toolbox.add_native(
        'use_skill',
        'Load a skill (a reusable instruction package) by name and follow it. '
        'Available skills are listed in the system prompt.',
        USE_SKILL_SCHEMA, use_skill)
    toolbox.add_native(
        'create_skill',
        'Create a new skill package the user asked for: reusable '
        'instructions saved to the instance skills directory, listed in '
        'future conversations.',
        CREATE_SKILL_SCHEMA, create_skill)
    toolbox.add_native(
        'update_skill',
        'Rewrite an existing skill\'s instructions. Editing a bundled skill '
        'forks it to the instance directory first (the shipped copy is '
        'never modified).',
        UPDATE_SKILL_SCHEMA, update_skill)
    toolbox.add_native(
        'delete_skill',
        'Delete an instance skill (bundled skills cannot be deleted).',
        DELETE_SKILL_SCHEMA, delete_skill)
