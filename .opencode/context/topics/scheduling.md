# Scheduling

> Algorithm in `src/scheduler.py`. Entry point `schedule_tasks(tasks, external_events, space_constraints)`.

## Inputs
- `tasks`: list of `Task` model objects ( SQLAlchemy instances) — caller passes non-completed tasks.
- `external_events`: list of `{start, end}` datetime dicts from `fetch_external_events` + any pre-scheduled external calendar items.
- `space_constraints`: dict mapping **space name** (not id) → time-constraint list (from `Space.get_time_constraints()`).

## Algorithm
1. **Split**: frozen tasks (with both `scheduled_start` and `scheduled_end`) are treated as immutable busy slots; non-frozen tasks are candidates for placement.
2. **Sort** non-frozen by `(-priority, deadline or datetime.max, created_at)` — highest priority first, then nearest deadline, then FIFO.
3. **Grid anchor**: `current_time = round_to_next_30min(datetime.now())` — all slots align to 30-minute boundaries.
4. **Busy pool**: seed with external events + frozen-task windows, then each newly placed task appends its slot and the pool is re-sorted by start.
5. **Placement**: for each task, `find_next_available_slot` walks forward from `current_time` (or deadline-aware start) in 30-min steps, skipping slots that overlap any busy entry or fall outside the task's space time constraints (`is_within_space_constraints`, `get_next_valid_time_for_space`). Duration defaults to 60 minutes when `estimated_duration` is falsy.

## Key helpers
- `round_to_next_30min(dt)` — ceil to next :00 or :30.
- `slots_overlap(a_start, a_end, b_start, b_end)` — busy-slot intersection test.
- `is_within_space_constraints(dt, space_name, constraints)` — is `dt` inside any allowed window for that space.
- `get_next_valid_time_for_space(dt, space_name, constraints)` — jump forward to the next slot that satisfies the space's windows.
- `find_next_available_slot(start, duration, busy_slots, space_name, constraints, deadline)` — the main search loop.

## Caveats
- **No timezone handling**: all datetimes are naive server-local. `calendar_integration` strips tzinfo from ICS events; `app.parse_iso_datetime` strips the `Z` (legacy UTC) without conversion. Frontend sends local-naive datetimes.
- **`Task.space` (legacy string) is used by the scheduler**, not `space_id` — `app.py` builds `space_constraints` keyed by space name (via `space_rel.name` fallback). Keep that name lookup intact when refactoring.
- **Deadline is a soft input** to slot search, not a hard constraint — a task may still be scheduled after its deadline if no earlier slot is free.
- **Re-schedule scope**: there is no per-task reschedule endpoint; clients call `POST /api/schedule` to re-plan all non-frozen tasks at once. Filters ("reschedule only current filter") are a TODO.
