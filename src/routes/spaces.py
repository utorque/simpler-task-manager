"""Space CRUD routes."""

from flask import Blueprint, jsonify, request

from audit import record_change
from auth import login_required
from models import db, Space

spaces_bp = Blueprint('spaces', __name__)


@spaces_bp.route('/api/spaces', methods=['GET'])
@login_required
def get_spaces():
    spaces = Space.query.all()
    return jsonify([space.to_dict() for space in spaces])


@spaces_bp.route('/api/spaces', methods=['POST'])
@login_required
def create_space():
    data = request.json

    space = Space(
        name=data['name'],
        description=data.get('description', '')
    )
    space.set_time_constraints(data.get('time_constraints', []))

    db.session.add(space)
    db.session.flush()
    record_change('create', 'space', space.id, new=space.to_dict())
    db.session.commit()

    return jsonify(space.to_dict()), 201


@spaces_bp.route('/api/spaces/<int:space_id>', methods=['PUT'])
@login_required
def update_space(space_id):
    space = Space.query.get_or_404(space_id)
    old_value = space.to_dict()
    data = request.json

    if 'name' in data:
        space.name = data['name']
    if 'description' in data:
        space.description = data['description']
    if 'time_constraints' in data:
        space.set_time_constraints(data['time_constraints'])

    record_change('update', 'space', space.id, old=old_value, new=space.to_dict())
    db.session.commit()
    return jsonify(space.to_dict())


@spaces_bp.route('/api/spaces/<int:space_id>', methods=['DELETE'])
@login_required
def delete_space(space_id):
    space = Space.query.get_or_404(space_id)
    old_value = space.to_dict()
    db.session.delete(space)
    record_change('delete', 'space', space_id, old=old_value)
    db.session.commit()
    return jsonify({'success': True})
