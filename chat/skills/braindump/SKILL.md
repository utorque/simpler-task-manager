---
name: braindump
description: Turn a messy braindump (pasted text or attached file) into structured tasks and a tidy note.
---

# Braindump capture

The user dumps unstructured thoughts (pasted text, a voice-note transcript,
an attached file). Turn it into workspace structure WITHOUT losing anything.

1. Read the whole dump first. Identify: actionable items, reference
   information, open questions, and junk.
2. Propose a task list: title, space (infer from the space filter and the
   content; ask when genuinely unclear), priority 0-10, deadline only when
   the text implies one, subtasks for multi-step items. Show the list and
   ask for a quick yes/adjust.
3. On confirmation, create the tasks (`simpler__create_task`) — one call per
   task, statuses `todo`.
4. Reference information and open questions become ONE tidy markdown note
   (`simpler__create_note`) titled after the dump's topic: `##` sections,
   bullet lists, bold key points. Do not invent facts; keep the user's
   wording for anything ambiguous.
5. Reply with a compact recap: N tasks created (one line each), note title,
   and anything you deliberately dropped as junk.
