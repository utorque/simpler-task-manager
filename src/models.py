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
    priority = db.Column(db.Integer, default=0)  # Higher number = higher priority
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to Space
    space_rel = db.relationship('Space', backref='tasks', foreign_keys=[space_id])

    def apply_status(self, status):
        """Set the kanban status and keep `completed` (+ completed_at) in sync."""
        if status not in TASK_STATUSES:
            raise ValueError(f"invalid status {status!r}, expected one of {TASK_STATUSES}")
        self.status = status
        self.completed = (status == 'done')
        self._sync_completed_at()

    def apply_completed(self, completed):
        """Legacy write path: setting `completed` derives `status`."""
        self.completed = bool(completed)
        if self.completed:
            self.status = 'done'
        elif self.status == 'done':
            self.status = 'todo'
        self._sync_completed_at()

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
            'completed': self.completed,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'frozen': self.frozen,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
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

    def to_dict(self):
        return {
            'id': self.id,
            'space_id': self.space_id,
            'title': self.title,
            'content_markdown': self.content_markdown or '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
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
