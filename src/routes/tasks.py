"""Task CRUD, AI parse, freeze, and reorder routes."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from ai_parser import parse_task_with_ai
from audit import record_change
from auth import login_required
from datetime_utils import parse_iso_datetime
from models import db, Task
from prompt_context import build_task_parse_prompt

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    include_completed = request.args.get('include_completed', 'false').lower() == 'true'

    query = Task.query
    if not include_completed:
        query = query.filter_by(completed=False)

    tasks = query.order_by(Task.priority.desc(), Task.deadline.asc()).all()
    return jsonify([task.to_dict() for task in tasks])


@tasks_bp.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    data = request.json

    task = Task(
        title=data['title'],
        description=data.get('description'),
        space_id=data.get('space_id'),
        priority=data.get('priority', 0),
        deadline=parse_iso_datetime(data.get('deadline')),
        estimated_duration=data.get('estimated_duration', 60)
    )

    db.session.add(task)
    db.session.flush()
    record_change('create', 'task', task.id, new=task.to_dict())
    db.session.commit()

    return jsonify(task.to_dict()), 201


@tasks_bp.route('/api/tasks/parse', methods=['POST'])
@login_required
def parse_task():
    data = request.json
    text = data.get('text')
    space_hint = data.get('space_hint')

    if not text:
        return jsonify({'error': 'No text provided'}), 400

    system_prompt = build_task_parse_prompt(space_hint=space_hint)

    # parse_task_with_ai returns a list of tasks
    tasks_data = parse_task_with_ai(text, system_prompt)

    created_tasks = []
    for task_data in tasks_data:
        task = Task(
            title=task_data['title'],
            description=task_data.get('description'),
            space_id=task_data.get('space_id'),
            priority=task_data.get('priority', 0),
            deadline=parse_iso_datetime(task_data.get('deadline')),
            estimated_duration=task_data.get('estimated_duration', 60)
        )

        db.session.add(task)
        db.session.flush()
        record_change('create', 'task', task.id, new=task.to_dict(), actor='ai')
        created_tasks.append(task)

    db.session.commit()

    # If only one task, return it directly for backward compatibility
    if len(created_tasks) == 1:
        return jsonify(created_tasks[0].to_dict()), 201
    return jsonify([task.to_dict() for task in created_tasks]), 201


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    old_value = task.to_dict()

    data = request.json

    if 'title' in data:
        task.title = data['title']
    if 'description' in data:
        task.description = data['description']
    if 'space_id' in data:
        task.space_id = data['space_id']
    if 'priority' in data:
        task.priority = data['priority']
    if 'deadline' in data:
        task.deadline = parse_iso_datetime(data.get('deadline'))
    if 'estimated_duration' in data:
        task.estimated_duration = data['estimated_duration']
    if 'scheduled_start' in data:
        task.scheduled_start = parse_iso_datetime(data.get('scheduled_start'))
    if 'scheduled_end' in data:
        task.scheduled_end = parse_iso_datetime(data.get('scheduled_end'))
    if 'completed' in data:
        task.completed = data['completed']
    if 'frozen' in data:
        task.frozen = data['frozen']

    record_change('update', 'task', task.id, old=old_value, new=task.to_dict())
    db.session.commit()

    return jsonify(task.to_dict())


@tasks_bp.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    old_value = task.to_dict()

    db.session.delete(task)
    record_change('delete', 'task', task_id, old=old_value)
    db.session.commit()

    return jsonify({'success': True})


@tasks_bp.route('/api/tasks/<int:task_id>/toggle-freeze', methods=['POST'])
@login_required
def toggle_task_freeze(task_id):
    task = Task.query.get_or_404(task_id)
    old_value = task.to_dict()

    task.frozen = not task.frozen
    record_change('freeze' if task.frozen else 'unfreeze', 'task', task.id,
                  old=old_value, new=task.to_dict())
    db.session.commit()

    return jsonify({'success': True, 'frozen': task.frozen})


@tasks_bp.route('/api/tasks/freeze-day', methods=['POST'])
@login_required
def freeze_day():
    data = request.json
    date_str = data.get('date')

    if not date_str:
        return jsonify({'error': 'No date provided'}), 400

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid date format. Expected YYYY-MM-DD'}), 400

    tasks_on_day = Task.query.filter(
        db.func.date(Task.scheduled_start) == target_date
    ).all()

    if not tasks_on_day:
        return jsonify({'success': True, 'count': 0, 'message': 'No tasks found on this day'})

    # If all are frozen, unfreeze them; otherwise freeze all
    all_frozen = all(task.frozen for task in tasks_on_day)
    new_frozen_state = not all_frozen

    for task in tasks_on_day:
        old_value = task.to_dict()
        task.frozen = new_frozen_state
        record_change('freeze' if new_frozen_state else 'unfreeze', 'task', task.id,
                      old=old_value, new=task.to_dict())

    db.session.commit()

    return jsonify({
        'success': True,
        'count': len(tasks_on_day),
        'frozen': new_frozen_state
    })


@tasks_bp.route('/api/tasks/reorder', methods=['POST'])
@login_required
def reorder_tasks():
    data = request.json
    task_ids = data.get('task_ids', [])

    # Update priorities based on order (higher index = higher priority)
    for index, task_id in enumerate(reversed(task_ids)):
        task = db.session.get(Task, task_id)
        if task:
            old_value = task.to_dict()
            task.priority = index
            record_change('reorder', 'task', task.id, old=old_value, new=task.to_dict())

    db.session.commit()
    return jsonify({'success': True})
