"""Live IMAP fetch (stdlib imaplib + email, no new dependency).

Mirrors calendar_integration's live-ICS pattern: nothing is persisted, every
open of a mailbox fetches fresh. Messages are transient DTOs:

    {uid, subject, from, date, snippet, unread}

and `fetch_message_body` returns the same DTO plus a full `body` for the
email-to-task flow. Plaintext passwords only ever live in memory for the
duration of one IMAP call.
"""

import email
import imaplib
from email.header import decode_header

SNIPPET_LEN = 200


def _connect(host, port, username, password, use_ssl=True):
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)
        try:
            conn.starttls()
        except Exception:
            pass  # server without STARTTLS: proceed plain (user's explicit choice)
    conn.login(username, password)
    return conn


def _decode_header_value(value):
    if not value:
        return ''
    out = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            out.append(text.decode(charset or 'utf-8', errors='replace'))
        else:
            out.append(text)
    return ''.join(out)


def _plain_text_body(msg):
    """Best-effort text/plain extraction (first non-attachment part)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and not part.get('Content-Disposition'):
                payload = part.get_payload(decode=True)
                if payload is not None:
                    return payload.decode(part.get_content_charset() or 'utf-8',
                                          errors='replace')
        return ''
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ''
    return payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')


def _message_dto(uid, raw_bytes, flags, include_body=False):
    msg = email.message_from_bytes(raw_bytes)
    body = _plain_text_body(msg)
    dto = {
        'uid': uid,
        'subject': _decode_header_value(msg.get('Subject')),
        'from': _decode_header_value(msg.get('From')),
        'date': msg.get('Date') or '',
        'snippet': ' '.join(body.split())[:SNIPPET_LEN],
        'unread': b'\\Seen' not in (flags or b''),
    }
    if include_body:
        dto['body'] = body
    return dto


def fetch_messages(host, port, username, password, use_ssl=True, limit=30):
    """Fetch the newest `limit` INBOX messages as transient DTOs."""
    conn = _connect(host, port, username, password, use_ssl)
    try:
        conn.select('INBOX', readonly=True)
        _typ, data = conn.uid('search', None, 'ALL')
        uids = data[0].split() if data and data[0] else []
        recent = list(reversed(uids[-limit:]))

        messages = []
        for uid in recent:
            _typ, msg_data = conn.uid('fetch', uid, '(FLAGS BODY.PEEK[])')
            if not msg_data or msg_data[0] is None:
                continue
            flags = msg_data[0][0] if isinstance(msg_data[0], tuple) else b''
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b''
            messages.append(_message_dto(uid.decode('ascii'), raw, flags))
        return messages
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_message_body(host, port, username, password, uid, use_ssl=True):
    """Fetch one message (by UID) including its full plain-text body."""
    conn = _connect(host, port, username, password, use_ssl)
    try:
        conn.select('INBOX', readonly=True)
        _typ, msg_data = conn.uid('fetch', uid.encode('ascii'), '(FLAGS BODY.PEEK[])')
        if not msg_data or msg_data[0] is None:
            return None
        flags = msg_data[0][0] if isinstance(msg_data[0], tuple) else b''
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b''
        return _message_dto(uid, raw, flags, include_body=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
