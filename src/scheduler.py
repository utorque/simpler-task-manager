"""Auto-scheduling algorithm — pure over plain data (no ORM knowledge).

The scheduler consumes SchedulableTask dicts (see `to_schedulable`) and a
`space_constraints` mapping keyed by space id. Routes adapt ORM `Task` rows at
the seam with `to_schedulable`; tests hand-build the dicts directly.
"""

from datetime import datetime, timedelta

# The fields the scheduler reads. `to_schedulable` produces exactly this shape.
SCHEDULABLE_FIELDS = (
    'id', 'space_id', 'priority', 'deadline', 'created_at',
    'estimated_duration', 'frozen', 'scheduled_start', 'scheduled_end',
)


def to_schedulable(task):
    """Adapt an ORM Task (or any object with these attrs) to the scheduler's
    plain-dict input shape."""
    return {field: getattr(task, field) for field in SCHEDULABLE_FIELDS}


def round_to_next_30min(dt):
    """Round datetime up to next 30-minute boundary, or keep if already aligned."""
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % 30
    if remainder == 0:
        return dt
    return dt + timedelta(minutes=30 - remainder)


def schedule_tasks(tasks, external_events, space_constraints, now=None):
    """
    Schedule tasks based on priority, deadlines, and space constraints.

    Args:
        tasks: List of SchedulableTask dicts (see `to_schedulable`)
        external_events: List of external calendar events (dicts with start, end)
        space_constraints: Dict of space id -> list of time constraints
        now: Injectable clock for tests; defaults to datetime.now()

    Returns:
        List of dicts with task id, scheduled_start, and scheduled_end
    """
    scheduled_tasks = []

    frozen_tasks = [t for t in tasks if t['frozen'] and t['scheduled_start'] and t['scheduled_end']]
    non_frozen_tasks = [t for t in tasks if not t['frozen']]

    sorted_tasks = sorted(
        non_frozen_tasks,
        key=lambda t: (
            -(t['priority'] or 0),
            t['deadline'] if t['deadline'] else datetime.max,
            t['created_at']
        )
    )

    current_time = round_to_next_30min(now or datetime.now())

    busy_slots = [{'start': event['start'], 'end': event['end']} for event in external_events]

    for frozen_task in frozen_tasks:
        busy_slots.append({
            'start': frozen_task['scheduled_start'],
            'end': frozen_task['scheduled_end']
        })

    for task in sorted_tasks:
        duration = timedelta(minutes=task['estimated_duration'] or 60)
        deadline = task['deadline']

        slot_start = find_next_available_slot(
            current_time,
            duration,
            busy_slots,
            task['space_id'],
            space_constraints,
            deadline
        )

        if slot_start:
            slot_end = slot_start + duration

            scheduled_tasks.append({
                'id': task['id'],
                'scheduled_start': slot_start,
                'scheduled_end': slot_end
            })

            busy_slots.append({
                'start': slot_start,
                'end': slot_end
            })

            busy_slots.sort(key=lambda x: x['start'])

    return scheduled_tasks


def find_next_available_slot(start_time, duration, busy_slots, space_id, space_constraints, deadline=None):
    """
    Find the next available time slot that satisfies all constraints.
    """
    current = start_time
    max_search_days = 90

    if deadline:
        max_search_time = deadline - duration
    else:
        max_search_time = start_time + timedelta(days=max_search_days)

    while current < max_search_time:
        slot_end = current + duration

        if not is_within_space_constraints(current, slot_end, space_id, space_constraints):
            current = get_next_valid_time_for_space(current, space_id, space_constraints)
            if current is None:
                return None
            continue

        is_available = True
        for busy in busy_slots:
            if slots_overlap(current, slot_end, busy['start'], busy['end']):
                is_available = False
                current = round_to_next_30min(busy['end'])
                break

        if is_available:
            return current

    return None


def slots_overlap(start1, end1, start2, end2):
    """Check if two time slots overlap."""
    return start1 < end2 and end1 > start2


def is_within_space_constraints(start, end, space_id, space_constraints):
    """
    Check if a time slot is within the constraints for a given space.

    Space constraints format:
    {
        <space_id>: [
            {'day': 0, 'start': '09:00', 'end': '17:00'},  # Monday
            {'day': 2, 'start': '18:00', 'end': '22:00'}   # Wednesday
        ]
    }

    day: 0=Monday, 1=Tuesday, ..., 6=Sunday
    """
    if space_id is None or space_id not in space_constraints:
        return True

    constraints = space_constraints[space_id]

    if not constraints:
        return True

    for constraint in constraints:
        if start.weekday() == constraint['day']:
            start_hour, start_minute = map(int, constraint['start'].split(':'))
            end_hour, end_minute = map(int, constraint['end'].split(':'))

            constraint_start = start.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            constraint_end = start.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)

            if start >= constraint_start and end <= constraint_end:
                return True

    return False


def get_next_valid_time_for_space(current, space_id, space_constraints):
    """
    Get the next valid time for a space based on its constraints.
    """
    if space_id is None or space_id not in space_constraints:
        return current

    constraints = space_constraints[space_id]

    if not constraints:
        return current

    for days_ahead in range(90):
        check_time = current + timedelta(days=days_ahead)

        for constraint in constraints:
            if check_time.weekday() == constraint['day']:
                start_hour, start_minute = map(int, constraint['start'].split(':'))
                constraint_start = check_time.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)

                if constraint_start >= current:
                    return constraint_start

    return None
