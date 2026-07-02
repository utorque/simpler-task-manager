"""Scheduler tests over the SchedulableTask seam (architecture review #2).

The scheduler is pure-over-data: tests hand-build plain dicts, no DB needed.
"""

from datetime import datetime, timedelta

from scheduler import schedule_tasks, to_schedulable

# A Monday 08:00 — fixed clock so weekday-based constraints are deterministic.
NOW = datetime(2026, 6, 29, 8, 0)


def make_task(id=1, space_id=None, priority=0, deadline=None, created_at=None,
              estimated_duration=60, frozen=False, scheduled_start=None,
              scheduled_end=None):
    return {
        'id': id,
        'space_id': space_id,
        'priority': priority,
        'deadline': deadline,
        'created_at': created_at or NOW - timedelta(days=1),
        'estimated_duration': estimated_duration,
        'frozen': frozen,
        'scheduled_start': scheduled_start,
        'scheduled_end': scheduled_end,
    }


def test_higher_priority_scheduled_first():
    low = make_task(id=1, priority=1)
    high = make_task(id=2, priority=9)
    result = schedule_tasks([low, high], [], {}, now=NOW)
    starts = {r['id']: r['scheduled_start'] for r in result}
    assert starts[2] < starts[1]


def test_scheduled_slots_do_not_overlap_busy_external_events():
    task = make_task(id=1, estimated_duration=60)
    busy = [{'start': NOW, 'end': NOW + timedelta(hours=2)}]
    result = schedule_tasks([task], busy, {}, now=NOW)
    assert len(result) == 1
    assert result[0]['scheduled_start'] >= busy[0]['end']


def test_frozen_task_is_not_moved_and_blocks_its_slot():
    frozen = make_task(id=1, frozen=True,
                       scheduled_start=NOW, scheduled_end=NOW + timedelta(hours=1))
    other = make_task(id=2)
    result = schedule_tasks([frozen, other], [], {}, now=NOW)
    ids = [r['id'] for r in result]
    assert 1 not in ids  # frozen task untouched
    other_slot = next(r for r in result if r['id'] == 2)
    assert other_slot['scheduled_start'] >= frozen['scheduled_end']


def test_space_constraints_keyed_by_space_id():
    # Space 7 only allows Wednesday (day index 2) 18:00-22:00.
    constraints = {7: [{'day': 2, 'start': '18:00', 'end': '22:00'}]}
    task = make_task(id=1, space_id=7, estimated_duration=60)
    result = schedule_tasks([task], [], constraints, now=NOW)
    assert len(result) == 1
    start = result[0]['scheduled_start']
    assert start.weekday() == 2
    assert start.hour >= 18
    assert (start + timedelta(hours=1)).hour <= 22


def test_task_with_impossible_deadline_is_left_unscheduled():
    task = make_task(id=1, deadline=NOW - timedelta(hours=1))
    result = schedule_tasks([task], [], {}, now=NOW)
    assert result == []


def test_to_schedulable_adapts_orm_shape():
    class FakeTask:
        id = 3
        space_id = 2
        priority = 5
        deadline = None
        created_at = NOW
        estimated_duration = 30
        frozen = False
        scheduled_start = None
        scheduled_end = None

    d = to_schedulable(FakeTask())
    assert d == {
        'id': 3, 'space_id': 2, 'priority': 5, 'deadline': None,
        'created_at': NOW, 'estimated_duration': 30, 'frozen': False,
        'scheduled_start': None, 'scheduled_end': None,
    }
