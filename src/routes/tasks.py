"""Task CRUD, AI parse, freeze, and reorder routes."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from ai_parser import parse_task_with_ai, select_tasks_with_ai
from audit import record_change
from auth import login_required
from datetime_utils import parse_iso_datetime
from models import db, Task, TASK_STATUSES
from prompt_context import build_task_parse_prompt, resolve_space

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

    status = data.get('status', 'todo')
    if status not in TASK_STATUSES:
        return jsonify({'error': f"invalid status {status!r}, expected one of {list(TASK_STATUSES)}"}), 400

    task = Task(
        title=data['title'],
        description=data.get('description'),
        space_id=data.get('space_id'),
        priority=data.get('priority', 0),
        deadline=parse_iso_datetime(data.get('deadline')),
        estimated_duration=data.get('estimated_duration', 60)
    )
    task.apply_status(status)

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
    restrict_space = data.get('restrict_space')
    force_status = data.get('force_status')

    if not text:
        return jsonify({'error': 'No text provided'}), 400

    # Column-placement override (kanban AI inline-create). Validated up-front so
    # an invalid status creates nothing, matching the create_task contract.
    if force_status is not None and force_status not in TASK_STATUSES:
        return jsonify({'error': f"invalid status {force_status!r}, expected one of {list(TASK_STATUSES)}"}), 400

    system_prompt = build_task_parse_prompt(
        space_hint=space_hint, restrict_space=restrict_space
    )

    # Resolve the restrict_space filter once (so we can default AI drafts that
    # came back without a space_id to the scoped space — matches the user's
    # intent when typing into a space-filtered board, and keeps the new task
    # visible on that board). None when no/ unresolved filter.
    scoped_space = resolve_space(restrict_space)

    # parse_task_with_ai returns a list of tasks
    tasks_data = parse_task_with_ai(text, system_prompt)

    created_tasks = []
    for task_data in tasks_data:
        space_id = task_data.get('space_id')
        if space_id is None and scoped_space is not None:
            # AI returned no space but the prompt was hard-scoped to one space;
            # default to it so the task lands where the user typed.
            space_id = scoped_space.id
        task = Task(
            title=task_data['title'],
            description=task_data.get('description'),
            space_id=space_id,
            priority=task_data.get('priority', 0),
            deadline=parse_iso_datetime(task_data.get('deadline')),
            estimated_duration=task_data.get('estimated_duration', 60)
        )

        db.session.add(task)
        db.session.flush()
        # Apply the client's column placement BEFORE the audit snapshot so the
        # recorded `new` reflects the final status. actor stays 'ai' — the task
        # was AI-drafted; the status override is deterministic placement, not a
        # user-authored edit. Single create row either way.
        if force_status is not None:
            task.apply_status(force_status)
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
        # Clamp to [0,10] at the seam so every caller (badge editor, modal,
        # reorder) gets the same guarantee — see PRD 001 T11 / G4.
        try:
            priority = int(data['priority'])
        except (TypeError, ValueError):
            return jsonify({'error': f"invalid priority {data['priority']!r}, expected an integer"}), 400
        task.priority = max(0, min(10, priority))
    if 'deadline' in data:
        task.deadline = parse_iso_datetime(data.get('deadline'))
    if 'estimated_duration' in data:
        task.estimated_duration = data['estimated_duration']
    if 'scheduled_start' in data:
        task.scheduled_start = parse_iso_datetime(data.get('scheduled_start'))
    if 'scheduled_end' in data:
        task.scheduled_end = parse_iso_datetime(data.get('scheduled_end'))
    # status is the single source of truth for done-ness; when both are sent,
    # status wins. Setting `completed` alone (legacy callers) derives status.
    if 'status' in data:
        if data['status'] not in TASK_STATUSES:
            return jsonify({'error': f"invalid status {data['status']!r}, expected one of {list(TASK_STATUSES)}"}), 400
        task.apply_status(data['status'])
    elif 'completed' in data:
        task.apply_completed(data['completed'])
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
    """Manual drag-reorder: nudge ONE task's priority (the dragged card).

    The client computes the priority that slots the dragged task between its
    new neighbours (fractional values allowed) and sends only that task —
    reordering never rewrites the rest of the list.
    """
    data = request.json or {}
    task_id = data.get('task_id')
    priority = data.get('priority')

    if task_id is None or priority is None:
        return jsonify({'error': 'task_id and priority are required'}), 400
    try:
        priority = float(priority)
    except (TypeError, ValueError):
        return jsonify({'error': f"invalid priority {data['priority']!r}, expected a number"}), 400

    task = db.session.get(Task, task_id)
    if task is None:
        return jsonify({'error': f'task {task_id} not found'}), 404

    old_value = task.to_dict()
    task.priority = max(0.0, min(10.0, priority))
    record_change('reorder', 'task', task.id, old=old_value, new=task.to_dict())
    db.session.commit()

    return jsonify(task.to_dict())


@tasks_bp.route('/api/tasks/auto-doing', methods=['POST'])
@login_required
def auto_select_doing():
    """AI auto-select for the Doing column: given a free-text intent ("what do
    you want to do?"), pick the matching TODO tasks and move them to doing.

    `space_ids` (optional) restricts the candidates to those spaces so a
    space-filtered board never pulls in tasks it isn't showing.
    """
    data = request.json or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    space_ids = data.get('space_ids')

    query = Task.query.filter_by(status='todo')
    if space_ids:
        query = query.filter(Task.space_id.in_(space_ids))
    candidates = query.all()

    if not candidates:
        return jsonify({'moved': []})

    selected_ids = select_tasks_with_ai(
        text,
        [task.to_dict() for task in candidates],
        current_app.config['TASK_SELECTION_PROMPT'],
    )
    if selected_ids is None:
        return jsonify({'error': 'AI could not select tasks — try again or drag them manually'}), 502

    by_id = {task.id: task for task in candidates}
    moved = []
    for task_id in selected_ids:
        task = by_id[task_id]  # select_tasks_with_ai guarantees candidate ids
        old_value = task.to_dict()
        task.apply_status('doing')
        record_change('update', 'task', task.id, old=old_value, new=task.to_dict(), actor='ai')
        moved.append(task)

    db.session.commit()
    return jsonify({'moved': [task.to_dict() for task in moved]})
