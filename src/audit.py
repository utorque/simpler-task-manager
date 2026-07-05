"""The audited-write seam (architecture review candidate 1).

Every mutation route used to hand-roll a 6-7 line ChangeLog stanza with a
second commit. `record_change` replaces all of them: it queues the audit row
in the CURRENT session so the entity mutation and its audit trail land in ONE
transaction — the caller commits once.

Usage in a route:

    task.title = 'new'
    record_change('update', 'task', task.id, old=old_dict, new=task.to_dict())
    db.session.commit()

For creates, flush first so the entity has an id:

    db.session.add(task)
    db.session.flush()
    record_change('create', 'task', task.id, new=task.to_dict())
    db.session.commit()
"""

import json

from flask import g, has_app_context

from models import db, ChangeLog


def record_change(action, entity_type, entity_id, old=None, new=None, actor=None):
    """Queue a ChangeLog row in the current session; the caller commits.

    `old` / `new` are plain dicts (usually `entity.to_dict()`), serialized
    here. `actor` records who drove the mutation: 'user' for direct UI/API
    edits, 'ai' for AI-created entities (parse, email-to-task), 'agent' for
    bearer-token mutations (Hermes via the MCP sidecar). When the caller does
    not pass one, the auth layer's `g.actor` wins (set on bearer auth),
    falling back to 'user'.
    """
    if actor is None:
        actor = (g.get('actor') if has_app_context() else None) or 'user'
    db.session.add(ChangeLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=json.dumps(old) if old is not None else None,
        new_value=json.dumps(new) if new is not None else None,
        actor=actor,
    ))
