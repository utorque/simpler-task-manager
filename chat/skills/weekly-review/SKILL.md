---
name: weekly-review
description: Guide the user through a structured weekly review of their board (stale tasks, priorities, next week's plan).
---

# Weekly review

Walk the user through a weekly review, one stage at a time — ask before
moving to the next stage, keep each stage short.

1. **Snapshot** — call `simpler__get_workspace_summary` and
   `simpler__list_tasks` (include_completed=true). Congratulate on what got
   done this week (completed_at within 7 days), concretely.
2. **Stale sweep** — find tasks not touched in 14+ days (updated_at) that are
   still todo/doing/blocked. For each, ask: still relevant? If not, suggest
   marking done or deleting (ask before deleting). If blocked, ask what
   unblocks it and offer to add that as a task.
3. **Priorities** — check the top-priority open tasks actually reflect what
   the user says matters next week; propose priority updates
   (`simpler__update_task`) and apply the confirmed ones.
4. **Plan** — ask what the 3 most important outcomes of next week are. Make
   sure each has a task (create missing ones), set deadlines where helpful,
   then offer to run `simpler__run_schedule`.
5. **Wrap-up** — post a short review summary as a note
   (`simpler__create_note`, space of the user's choice) titled
   "Weekly review YYYY-MM-DD".

Tone: encouraging, zero guilt about unfinished items. ADHD-friendly: small
steps, quick wins first.
