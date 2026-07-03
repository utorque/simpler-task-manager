"""Notes CRUD, Cleanify, and promote-to-task routes."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from ai_parser import cleanify_note_with_ai, parse_task_with_ai
from audit import record_change
from auth import login_required
from models import db, Note
from prompt_context import build_task_parse_prompt

notes_bp = Blueprint('notes', __name__)


@notes_bp.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    # `space_id` may be repeated (?space_id=1&space_id=3) to view several
    # spaces at once (Ctrl+click multi-select chips); absent = all spaces.
    space_ids = request.args.getlist('space_id', type=int)
    query = Note.query
    if space_ids:
        query = query.filter(Note.space_id.in_(space_ids))
    notes = query.order_by(Note.updated_at.desc()).all()
    return jsonify([note.to_dict() for note in notes])


@notes_bp.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.json or {}
    space_id = data.get('space_id')
    if space_id is None:
        return jsonify({'error': 'space_id is required'}), 400

    note = Note(
        space_id=space_id,
        title=data.get('title'),
        content_markdown=data.get('content_markdown', ''),
    )
    db.session.add(note)
    db.session.flush()
    record_change('create', 'note', note.id, new=note.to_dict())
    db.session.commit()

    return jsonify(note.to_dict())


@notes_bp.route('/api/notes/<int:note_id>', methods=['GET'])
@login_required
def get_note(note_id):
    note = Note.query.get_or_404(note_id)
    return jsonify(note.to_dict())


@notes_bp.route('/api/notes/<int:note_id>', methods=['PUT'])
@login_required
def update_note(note_id):
    note = Note.query.get_or_404(note_id)
    old_value = note.to_dict()
    data = request.json or {}

    if 'title' in data:
        note.title = data['title']
    if 'content_markdown' in data:
        note.content_markdown = data['content_markdown']
    if 'space_id' in data:
        note.space_id = data['space_id']

    record_change('update', 'note', note.id, old=old_value, new=note.to_dict())
    db.session.commit()

    return jsonify(note.to_dict())


@notes_bp.route('/api/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    old_value = note.to_dict()

    db.session.delete(note)
    record_change('delete', 'note', note_id, old=old_value)
    db.session.commit()

    return '', 204


@notes_bp.route('/api/notes/<int:note_id>/cleanify', methods=['POST'])
@login_required
def cleanify_note(note_id):
    note = Note.query.get_or_404(note_id)

    space = note.space_rel
    system_prompt = current_app.config['NOTES_CLEANIFY_PROMPT']
    system_prompt += (
        f"\n\nNote's Space context:\nName: {space.name}\n"
        f"Description: {space.description or ''}"
    )
    # The structured output puts the note's date below the title.
    note_date = (note.created_at or datetime.utcnow()).strftime('%Y-%m-%d')
    system_prompt += f"\n\nNote date (put below the title): {note_date}"

    content = cleanify_note_with_ai(note.content_markdown, system_prompt)
    return jsonify({'content': content})


@notes_bp.route('/api/notes/<int:note_id>/promote-to-task', methods=['POST'])
@login_required
def promote_note_to_task(note_id):
    note = Note.query.get_or_404(note_id)

    data = request.get_json(silent=True) or {}
    selected_text = data.get('selected_text')

    # Same space-list context the AI task creator sees.
    system_prompt = build_task_parse_prompt()

    # Reuse the existing AI parse path (no new AI code path; PRD decision G).
    drafts = parse_task_with_ai(selected_text, system_prompt)

    # Default each draft's space_id to the note's space_id when the LLM did not
    # pick one (default, NOT override — LLM-chosen spaces are left alone).
    for draft in drafts:
        if draft.get('space_id') is None:
            draft['space_id'] = note.space_id

    # Return the draft DTO list. The client opens a confirm modal pre-filled
    # with these drafts; the existing POST /api/tasks persists them. This
    # route persists NOTHING and does NOT modify the note.
    return jsonify(drafts)
