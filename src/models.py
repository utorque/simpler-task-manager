from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

# Application-level enum for Task.status (SQLite has no native ENUM).
TASK_STATUSES = ('todo', 'doing', 'blocked', 'done')


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    # LEGACY: no code reads or writes this column anymore (space_id is the
    # canonical relation). The column stays in the schema because migrate_db.py
    # is additive-only; its data is backfilled into space_id by a data fixup.
    space = db.Column(db.String(100))
    space_id = db.Column(db.Integer, db.ForeignKey('spaces.id'))  # Reference to Space table
    # Higher number = higher priority. Float: user-facing editing stays on the
    # integer 0-10 scale, but manual drag-reorder nudges the dragged task to a
    # fractional value between its new neighbours so ONLY that task changes.
    # (SQLite type affinity keeps prod's INTEGER-declared column storing
    # fractional REALs losslessly — no migration needed.)
    priority = db.Column(db.Float, default=0)
    deadline = db.Column(db.DateTime)
    estimated_duration = db.Column(db.Integer)  # in minutes
    scheduled_start = db.Column(db.DateTime)
    scheduled_end = db.Column(db.DateTime)
    # Kanban workflow state. Single source of truth for done-ness:
    # `completed` is kept in sync (completed ⇔ status == 'done') for the
    # calendar UI and legacy API callers.
    status = db.Column(db.String(20), default='todo', nullable=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)  # set when the task turns done, cleared when it un-dones
    frozen = db.Column(db.Boolean, default=False)  # Prevents rescheduling when True
    # Provenance: the note this task was promoted from (one-way — the note
    # knows nothing about its tasks). SQLite runs without PRAGMA foreign_keys,
    # so the ON DELETE SET NULL is enforced in the note delete route, not here.
    note_id = db.Column(db.Integer, db.ForeignKey('notes.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to Space
    space_rel = db.relationship('Space', backref='tasks', foreign_keys=[space_id])
    note_rel = db.relationship('Note', foreign_keys=[note_id], lazy='selectin')

    # Subtasks: checklist items under this task. selectin avoids N+1 on the
    # board's load-all-tasks query. delete-orphan: a subtask never outlives
    # its task.
    subtasks = db.relationship(
        'Subtask', backref='task', cascade='all, delete-orphan',
        order_by='Subtask.position, Subtask.id', lazy='selectin')

    def apply_status(self, status):
        """Set the kanban status and keep `completed` (+ completed_at) in sync."""
        if status not in TASK_STATUSES:
            raise ValueError(f"invalid status {status!r}, expected one of {TASK_STATUSES}")
        self.status = status
        self.completed = (status == 'done')
        if self.completed:
            # Two-way sync, manual direction: marking the task done checks
            # every remaining subtask.
            for subtask in self.subtasks:
                subtask.done = True
        self._sync_completed_at()

    def apply_completed(self, completed):
        """Legacy write path: setting `completed` derives `status`."""
        if completed:
            self.apply_status('done')
        elif self.status == 'done':
            self.apply_status('todo')
        else:
            self.completed = False
            self._sync_completed_at()

    def sync_status_from_subtasks(self):
        """Two-way sync, subtask direction. Call after any subtask mutation:
        all subtasks done ⇒ task done; an undone subtask on a done task ⇒
        back to doing. No-op for tasks without subtasks."""
        if not self.subtasks:
            return
        if all(subtask.done for subtask in self.subtasks):
            if self.status != 'done':
                self.apply_status('done')
        elif self.status == 'done':
            self.apply_status('doing')

    def _sync_completed_at(self):
        # First transition into done stamps the time; re-saving an
        # already-done task keeps the original finish time.
        if self.completed:
            if self.completed_at is None:
                self.completed_at = datetime.utcnow()
        else:
            self.completed_at = None

    def to_dict(self):
        # space_id is canonical; 'space' is a denormalized name echo for the UI.
        space_name = self.space_rel.name if self.space_rel else None

        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'space': space_name,  # For backward compatibility in UI
            'space_id': self.space_id,
            'priority': self.priority,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'estimated_duration': self.estimated_duration,
            'scheduled_start': self.scheduled_start.isoformat() if self.scheduled_start else None,
            'scheduled_end': self.scheduled_end.isoformat() if self.scheduled_end else None,
            'status': self.status or 'todo',
            'note_id': self.note_id,
            'note_title': self.note_rel.title if self.note_rel else None,
            'subtasks': [subtask.to_dict() for subtask in self.subtasks],
            'completed': self.completed,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'frozen': self.frozen,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Subtask(db.Model):
    """A checklist item under a Task. Title-only by design — no priority,
    deadline, or scheduling: subtasks are steps of one task, not tasks."""
    __tablename__ = 'subtasks'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    done = db.Column(db.Boolean, default=False, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)  # creation order
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'title': self.title,
            'done': self.done,
            'position': self.position,
        }


class Space(db.Model):
    __tablename__ = 'spaces'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)  # Plain text description of the space (context, purpose, etc.)
    # User-editable markdown injected into AI task prompts as guidance only
    # (see prompt_context.space_guidance_block) — never as task content.
    context_markdown = db.Column(db.Text, default='')
    time_constraints = db.Column(db.Text)  # JSON string of time constraints
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_time_constraints(self):
        if self.time_constraints:
            return json.loads(self.time_constraints)
        return []

    def set_time_constraints(self, constraints):
        self.time_constraints = json.dumps(constraints)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'context_markdown': self.context_markdown or '',
            'time_constraints': self.get_time_constraints(),
            'created_at': self.created_at.isoformat()
        }


class ChangeLog(db.Model):
    __tablename__ = 'change_logs'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)  # create, update, delete, reorder, freeze, unfreeze
    entity_type = db.Column(db.String(50), nullable=False)  # task, space, note, mailbox
    entity_id = db.Column(db.Integer)
    old_value = db.Column(db.Text)  # JSON string
    new_value = db.Column(db.Text)  # JSON string
    actor = db.Column(db.String(50), default='user')  # 'user' or 'ai'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'old_value': json.loads(self.old_value) if self.old_value else None,
            'new_value': json.loads(self.new_value) if self.new_value else None,
            'actor': self.actor,
            'timestamp': self.timestamp.isoformat()
        }


class Note(db.Model):
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey('spaces.id'), nullable=False)
    title = db.Column(db.String(500))
    content_markdown = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    space_rel = db.relationship('Space', backref='notes', foreign_keys=[space_id])

    # Public read-only share (0-or-1 per note). uselist=False makes it a scalar;
    # delete-orphan means dropping the note (or detaching the share) removes the
    # link so a stale token can never resolve to a note.
    share = db.relationship(
        'NoteShare', backref='note', uselist=False,
        cascade='all, delete-orphan', lazy='selectin')

    def to_dict(self):
        return {
            'id': self.id,
            'space_id': self.space_id,
            'title': self.title,
            'content_markdown': self.content_markdown or '',
            # Opaque token of the note's public share, or None when not shared.
            # The client builds the shareable URL from its own window.origin, so
            # to_dict stays request-context-free and proxy-agnostic.
            'public_share_token': self.share.token if self.share else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class NoteShare(db.Model):
    """A public, read-only share of a Note.

    One row per shared note (note_id is UNIQUE — creating a share for an
    already-shared note reuses the existing token). The random `token` is the
    only credential: anyone holding the `/n/<token>` URL can view the note's
    latest markdown, rendered read-only. Deleting the row ("stop sharing") is
    what revokes access — the token is not reused. No auth is attached to the
    row itself; there is a single owner (APP_PASSWORD) and every share is that
    owner's.
    """
    __tablename__ = 'note_shares'

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey('notes.id', ondelete='CASCADE'),
                        nullable=False, unique=True, index=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'note_id': self.note_id,
            'token': self.token,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Mailbox(db.Model):
    """A registered IMAP mailbox, linked to a Space.

    No inbox contents are persisted — messages are fetched live via IMAP on
    each open (mirrors the live-ICS pattern of CalendarSource). The account
    password is encrypted at rest (see crypto_utils); it is NEVER returned by
    any API — to_dict only exposes has_password.
    """
    __tablename__ = 'mailboxes'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(100), nullable=False)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, default=993)
    username = db.Column(db.String(255), nullable=False)
    password_encrypted = db.Column(db.Text, nullable=False)
    use_ssl = db.Column(db.Boolean, default=True)  # False = plain IMAP + STARTTLS
    space_id = db.Column(db.Integer, db.ForeignKey('spaces.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    space_rel = db.relationship('Space', backref='mailboxes', foreign_keys=[space_id])

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'has_password': bool(self.password_encrypted),
            'use_ssl': self.use_ssl,
            'space_id': self.space_id,
            'space': self.space_rel.name if self.space_rel else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CalendarSource(db.Model):
    __tablename__ = 'calendar_sources'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ics_url = db.Column(db.String(500), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_fetched = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'ics_url': self.ics_url,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat(),
            'last_fetched': self.last_fetched.isoformat() if self.last_fetched else None
        }
