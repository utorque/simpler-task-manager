"""Auto-schedule and change-log routes."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from auth import login_required
from calendar_integration import fetch_external_events
from models import db, Task, Space, ChangeLog, CalendarSource
from scheduler import schedule_tasks, to_schedulable

schedule_bp = Blueprint('schedule', __name__)


@schedule_bp.route('/api/schedule', methods=['POST'])
@login_required
def auto_schedule():
    # Optional scoping: `task_ids` restricts (re)scheduling to those tasks
    # (the board sends its displayed Doing tasks). Absent/None = schedule all.
    data = request.get_json(silent=True) or {}
    task_ids = data.get('task_ids')
    scoped_ids = set(task_ids) if task_ids is not None else None

    tasks = Task.query.filter_by(completed=False).order_by(
        Task.priority.desc(), Task.deadline.asc()).all()

    # Get external calendar events
    external_events = []
    calendar_sources = CalendarSource.query.filter_by(enabled=True).all()
    for source in calendar_sources:
        events = fetch_external_events(source.ics_url)
        external_events.extend(events)
        source.last_fetched = datetime.utcnow()

    db.session.commit()

    # Constraints keyed by space id — the scheduler never sees space names.
    spaces = Space.query.all()
    space_constraints = {space.id: space.get_time_constraints() for space in spaces}

    # The scheduler is pure-over-data: adapt ORM rows at the seam. Out-of-scope
    # tasks are marked frozen so the scheduler never moves them while their
    # existing slots still count as busy (no double-booking of scoped tasks).
    schedulables = []
    for t in tasks:
        schedulable = to_schedulable(t)
        if scoped_ids is not None and schedulable['id'] not in scoped_ids:
            schedulable['frozen'] = True
        schedulables.append(schedulable)

    scheduled_tasks = schedule_tasks(schedulables, external_events, space_constraints)

    for task_data in scheduled_tasks:
        task = db.session.get(Task, task_data['id'])
        if task:
            task.scheduled_start = task_data['scheduled_start']
            task.scheduled_end = task_data['scheduled_end']

    db.session.commit()

    return jsonify({'success': True, 'scheduled_tasks': len(scheduled_tasks)})


@schedule_bp.route('/api/logs', methods=['GET'])
@login_required
def get_logs():
    limit = request.args.get('limit', 100, type=int)
    logs = ChangeLog.query.order_by(ChangeLog.timestamp.desc()).limit(limit).all()
    return jsonify([log.to_dict() for log in logs])
