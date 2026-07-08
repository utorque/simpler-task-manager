"""Assistant settings API: the settings panel's backend (issue 003.07).

Thin HTTP wrappers over `chat.assistant_settings` (model list, reasoning
levels, system-prompt override) and `chat.skills` (authoring functions from
003.06), plus the read-only composition viewer built from the SAME layer
assembly the model's system prompt uses (`chainlit_app.
build_system_prompt_layers`) so the two can't drift.
"""

import asyncio
import os
from datetime import datetime

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Space

from chat import assistant_settings
from chat import skills as chat_skills

assistant_settings_bp = Blueprint('assistant_settings', __name__)


def _system_prompt_state(include_body: bool = True) -> dict:
    path = assistant_settings.system_prompt_path()
    is_override = (path == assistant_settings.system_prompt_override_path())
    try:
        last_modified = datetime.fromtimestamp(
            os.path.getmtime(path)).isoformat(timespec='seconds')
    except OSError:
        last_modified = None
    state = {'source': 'instance' if is_override else 'bundled',
             'last_modified': last_modified}
    if include_body:
        state['body'] = assistant_settings.load_system_prompt()
    return state


def _skill_summaries() -> list[dict]:
    return [{'name': s['name'], 'description': s['description'],
             'source': s['source']} for s in chat_skills.list_skills()]


def _composition_layers() -> list[dict]:
    """The system-prompt layers as the model would see them right now.
    Spaces come straight from the DB (this IS the workspace app — looping
    back through the HTTP API would call our own busy server); the toolbox
    is built the same way a chat turn builds it."""
    from chat import chainlit_app  # deferred: pulls in the chainlit runtime

    spaces = [space.to_dict() for space in Space.query.all()]

    async def assemble():
        toolbox = await chainlit_app.build_toolbox()
        return await chainlit_app.build_system_prompt_layers(
            toolbox=toolbox, spaces=spaces)

    return asyncio.run(assemble())


@assistant_settings_bp.route('/api/assistant/settings', methods=['GET'])
@login_required
def get_settings():
    return jsonify({
        'models': assistant_settings.available_models(),
        'reasoning_levels': assistant_settings.available_reasoning_levels(),
        'skills': _skill_summaries(),
        'system_prompt': _system_prompt_state(),
        'composition': {'layers': _composition_layers()},
    })


def _validated_string_list(payload) -> list[str] | None:
    if not isinstance(payload, list):
        return None
    items = [str(item).strip() for item in payload if str(item).strip()]
    return items or None


@assistant_settings_bp.route('/api/assistant/models', methods=['PUT'])
@login_required
def put_models():
    models = _validated_string_list(request.json)
    if models is None:
        return jsonify({'error': 'provide a non-empty list of model ids'}), 400
    assistant_settings.write_models(models)
    return jsonify({'models': assistant_settings.available_models()})


@assistant_settings_bp.route('/api/assistant/reasoning-levels', methods=['PUT'])
@login_required
def put_reasoning_levels():
    levels = _validated_string_list(request.json)
    if levels is None:
        return jsonify({'error': 'provide a non-empty list of levels'}), 400
    assistant_settings.write_reasoning_levels(levels)
    return jsonify({'reasoning_levels': assistant_settings.available_reasoning_levels()})


@assistant_settings_bp.route('/api/assistant/system-prompt', methods=['GET'])
@login_required
def get_system_prompt():
    return jsonify(_system_prompt_state())


@assistant_settings_bp.route('/api/assistant/system-prompt', methods=['PUT'])
@login_required
def put_system_prompt():
    data = request.json or {}
    body = data.get('body')
    if not isinstance(body, str) or not body.strip():
        return jsonify({'error': 'provide the prompt text in "body"'}), 400
    with open(assistant_settings.system_prompt_override_path(), 'w',
              encoding='utf-8') as f:
        f.write(body)
    return jsonify(_system_prompt_state(include_body=False))


@assistant_settings_bp.route('/api/assistant/system-prompt', methods=['DELETE'])
@login_required
def delete_system_prompt():
    assistant_settings.reset_system_prompt()
    return jsonify(_system_prompt_state(include_body=False))


def _find_skill(name: str):
    return next((s for s in chat_skills.list_skills()
                 if s['name'].lower() == (name or '').lower()), None)


@assistant_settings_bp.route('/api/assistant/skills', methods=['POST'])
@login_required
def create_skill_route():
    data = request.json or {}
    message = chat_skills.create_skill(
        name=data.get('name', ''),
        description=data.get('description', ''),
        body=data.get('body', ''),
        files=None)
    if message.startswith('TOOL ERROR'):
        return jsonify({'error': message.removeprefix('TOOL ERROR: ')}), 400
    skill = _find_skill(data.get('name', ''))
    return jsonify({'skill': {'name': skill['name'],
                              'description': skill['description'],
                              'source': skill['source']}}), 201


@assistant_settings_bp.route('/api/assistant/skills/<name>', methods=['PUT'])
@login_required
def update_skill_route(name):
    data = request.json or {}
    body = data.get('body')
    if not isinstance(body, str) or not body.strip():
        return jsonify({'error': 'provide the skill body'}), 400
    if _find_skill(name) is None:
        return jsonify({'error': f'no skill named {name!r}'}), 404
    message = chat_skills.update_skill(name, body=body,
                                       description=data.get('description'))
    if message.startswith('TOOL ERROR'):
        return jsonify({'error': message.removeprefix('TOOL ERROR: ')}), 400
    skill = _find_skill(name)
    return jsonify({'skill': {'name': skill['name'],
                              'description': skill['description'],
                              'source': skill['source']}})


@assistant_settings_bp.route('/api/assistant/skills/<name>', methods=['DELETE'])
@login_required
def delete_skill_route(name):
    existing = _find_skill(name)
    if existing is None:
        return jsonify({'error': f'no skill named {name!r}'}), 404
    if existing['source'] == 'bundled':
        return jsonify({'error': 'bundled skills cannot be deleted'}), 400
    message = chat_skills.delete_skill(name)
    if message.startswith('TOOL ERROR'):
        return jsonify({'error': message.removeprefix('TOOL ERROR: ')}), 400
    return jsonify({'ok': True})
