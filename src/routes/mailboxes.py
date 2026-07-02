"""Mailbox registration + live IMAP browsing + email-to-task.

Security posture (PrePRD decision G): passwords are Fernet-encrypted at rest
with a key derived from SECRET_KEY, decrypted only for the duration of one
IMAP call, and never returned by any endpoint (to_dict exposes has_password).
"""

from flask import Blueprint, current_app, jsonify, request

from ai_parser import email_to_task_with_ai
from audit import record_change
from auth import login_required
from crypto_utils import decrypt_secret, encrypt_secret, InvalidToken
from mail_integration import fetch_message_body, fetch_messages
from models import db, Mailbox
from prompt_context import spaces_context

mailboxes_bp = Blueprint('mailboxes', __name__)

MAX_MESSAGE_LIMIT = 100


def _mailbox_password(mailbox):
    return decrypt_secret(mailbox.password_encrypted, current_app.config['SECRET_KEY'])


@mailboxes_bp.route('/api/mailboxes', methods=['GET'])
@login_required
def get_mailboxes():
    mailboxes = Mailbox.query.order_by(Mailbox.label.asc()).all()
    return jsonify([m.to_dict() for m in mailboxes])


@mailboxes_bp.route('/api/mailboxes', methods=['POST'])
@login_required
def create_mailbox():
    data = request.json or {}
    for field in ('label', 'host', 'username', 'password'):
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    mailbox = Mailbox(
        label=data['label'],
        host=data['host'],
        port=data.get('port', 993),
        username=data['username'],
        password_encrypted=encrypt_secret(data['password'], current_app.config['SECRET_KEY']),
        use_ssl=data.get('use_ssl', True),
        space_id=data.get('space_id'),
    )
    db.session.add(mailbox)
    db.session.flush()
    record_change('create', 'mailbox', mailbox.id, new=mailbox.to_dict())
    db.session.commit()

    return jsonify(mailbox.to_dict()), 201


@mailboxes_bp.route('/api/mailboxes/<int:mailbox_id>', methods=['PUT'])
@login_required
def update_mailbox(mailbox_id):
    mailbox = Mailbox.query.get_or_404(mailbox_id)
    old_value = mailbox.to_dict()
    data = request.json or {}

    if 'label' in data:
        mailbox.label = data['label']
    if 'host' in data:
        mailbox.host = data['host']
    if 'port' in data:
        mailbox.port = data['port']
    if 'username' in data:
        mailbox.username = data['username']
    if 'use_ssl' in data:
        mailbox.use_ssl = data['use_ssl']
    if 'space_id' in data:
        mailbox.space_id = data['space_id']
    # Password only changes when a non-empty one is sent (the UI never
    # round-trips the stored one — it can't, it never receives it).
    if data.get('password'):
        mailbox.password_encrypted = encrypt_secret(
            data['password'], current_app.config['SECRET_KEY'])

    record_change('update', 'mailbox', mailbox.id, old=old_value, new=mailbox.to_dict())
    db.session.commit()

    return jsonify(mailbox.to_dict())


@mailboxes_bp.route('/api/mailboxes/<int:mailbox_id>', methods=['DELETE'])
@login_required
def delete_mailbox(mailbox_id):
    mailbox = Mailbox.query.get_or_404(mailbox_id)
    old_value = mailbox.to_dict()

    db.session.delete(mailbox)
    record_change('delete', 'mailbox', mailbox_id, old=old_value)
    db.session.commit()

    return jsonify({'success': True})


@mailboxes_bp.route('/api/mailboxes/<int:mailbox_id>/messages', methods=['GET'])
@login_required
def get_mailbox_messages(mailbox_id):
    mailbox = Mailbox.query.get_or_404(mailbox_id)
    limit = min(request.args.get('limit', 30, type=int), MAX_MESSAGE_LIMIT)

    try:
        password = _mailbox_password(mailbox)
    except InvalidToken:
        return jsonify({'error': 'Stored password cannot be decrypted '
                                 '(SECRET_KEY changed?). Re-enter the mailbox password.'}), 409

    try:
        messages = fetch_messages(
            mailbox.host, mailbox.port, mailbox.username, password,
            use_ssl=mailbox.use_ssl, limit=limit)
    except Exception as e:
        return jsonify({'error': f'IMAP fetch failed: {e}'}), 502

    return jsonify(messages)


@mailboxes_bp.route('/api/mailboxes/<int:mailbox_id>/messages/<uid>', methods=['GET'])
@login_required
def get_mailbox_message(mailbox_id, uid):
    """One message with its full plain-text body (live IMAP, read-only —
    opening it here does NOT mark it read on the server)."""
    mailbox = Mailbox.query.get_or_404(mailbox_id)

    try:
        password = _mailbox_password(mailbox)
    except InvalidToken:
        return jsonify({'error': 'Stored password cannot be decrypted '
                                 '(SECRET_KEY changed?). Re-enter the mailbox password.'}), 409

    try:
        message = fetch_message_body(
            mailbox.host, mailbox.port, mailbox.username, password,
            uid, use_ssl=mailbox.use_ssl)
    except Exception as e:
        return jsonify({'error': f'IMAP fetch failed: {e}'}), 502

    if message is None:
        return jsonify({'error': 'Message not found'}), 404

    return jsonify(message)


@mailboxes_bp.route('/api/mailboxes/<int:mailbox_id>/messages/<uid>/add-task', methods=['POST'])
@login_required
def email_to_task(mailbox_id, uid):
    """Derive task draft(s) from one email. Persists NOTHING — the client
    opens the task-confirm modal and the user commits via POST /api/tasks."""
    mailbox = Mailbox.query.get_or_404(mailbox_id)

    try:
        password = _mailbox_password(mailbox)
    except InvalidToken:
        return jsonify({'error': 'Stored password cannot be decrypted '
                                 '(SECRET_KEY changed?). Re-enter the mailbox password.'}), 409

    try:
        message = fetch_message_body(
            mailbox.host, mailbox.port, mailbox.username, password,
            uid, use_ssl=mailbox.use_ssl)
    except Exception as e:
        return jsonify({'error': f'IMAP fetch failed: {e}'}), 502

    if message is None:
        return jsonify({'error': 'Message not found'}), 404

    # Dedicated email prompt + the same space-list context as every other AI
    # task path.
    system_prompt = current_app.config['EMAIL_TO_TASK_PROMPT'] + "\n\n" + spaces_context()

    drafts = email_to_task_with_ai(message['subject'], message.get('body', ''), system_prompt)

    # Pre-tag with the mailbox's linked Space unless the LLM chose one.
    for draft in drafts:
        if draft.get('space_id') is None:
            draft['space_id'] = mailbox.space_id

    return jsonify(drafts)
