# Scheduling

> Algorithm in `src/scheduler.py`. Entry point `schedule_tasks(tasks, external_events, space_constraints, now=None)`. **Pure over plain data** — no ORM knowledge (architecture review candidate 2, applied 2026-07).

## Inputs
- `tasks`: list of **SchedulableTask dicts** (see `to_schedulable(task)` — the adapter routes use to convert ORM `Task` rows at the seam). Fields: `id, space_id, priority, deadline, created_at, estimated_duration, frozen, scheduled_start, scheduled_end`. Caller passes non-completed tasks.
- `external_events`: list of `{start, end}` datetime dicts from `fetch_external_events`.
- `space_constraints`: dict mapping **space id** → time-constraint list (from `Space.get_time_constraints()`). The scheduler never sees space names.
- `now`: injectable clock for tests; defaults to `datetime.now()`.

## Algorithm
1. **Split**: frozen tasks (with both `scheduled_start` and `scheduled_end`) are treated as immutable busy slots; non-frozen tasks are candidates for placement.
2. **Sort** non-frozen by `(-priority, deadline or datetime.max, created_at)` — highest priority first, then nearest deadline, then FIFO.
3. **Grid anchor**: `current_time = round_to_next_30min(now)` — all slots align to 30-minute boundaries.
4. **Busy pool**: seed with external events + frozen-task windows, then each newly placed task appends its slot and the pool is re-sorted by start.
5. **Placement**: for each task, `find_next_available_slot` walks forward from `current_time` in 30-min steps, skipping slots that overlap any busy entry or fall outside the task's space time constraints (`is_within_space_constraints`, `get_next_valid_time_for_space`). Duration defaults to 60 minutes when `estimated_duration` is falsy.

## Key helpers
- `to_schedulable(task)` — ORM (or any attr-bearing object) → plain dict; the ONLY place that knows the field list (`SCHEDULABLE_FIELDS`).
- `round_to_next_30min(dt)` — ceil to next :00 or :30.
- `slots_overlap(a_start, a_end, b_start, b_end)` — busy-slot intersection test.
- `is_within_space_constraints(start, end, space_id, constraints)` / `get_next_valid_time_for_space(dt, space_id, constraints)` — space-window logic, keyed by id.
- `find_next_available_slot(start, duration, busy_slots, space_id, constraints, deadline)` — the main search loop.

## Tests
`tests/test_scheduler.py` — hand-built dicts, no DB: priority ordering, busy-slot avoidance, frozen-task pinning, space-constraint windows, impossible deadlines, the adapter shape. This is the regression net for the open "not all tasks planned" investigation (`doc/TODO.md`).

## Caveats
- **No timezone handling**: all datetimes are naive server-local. `calendar_integration` strips tzinfo from ICS events; `datetime_utils.parse_iso_datetime` strips the `Z` (legacy UTC) without conversion. Frontend sends local-naive datetimes.
- **Deadline is a hard search bound**: `max_search_time = deadline - duration`, so a task whose deadline can't be met is left **unscheduled** (returned list simply omits it) — this is one suspected cause of "not all tasks planned".
- **Re-schedule scope**: there is no per-task reschedule endpoint; `POST /api/schedule` re-plans all non-frozen tasks at once, unless the body carries `task_ids` — then only those tasks are (re)placed and every other incomplete task is passed to the scheduler as frozen (its existing slot stays busy, it is never moved). The kanban board sends its currently displayed Doing tasks as `task_ids` (Schedule pressed from the board = plan what I'm doing now); every other view schedules everything. Route seam: `src/routes/schedule.py`; tests: `tests/test_schedule_scope.py`.
