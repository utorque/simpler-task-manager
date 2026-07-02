# Mail Module

> Space-linked IMAP mailboxes with live inbox browsing and email-to-task. PrePRD `000` decision G. Nothing about email is persisted except the mailbox registration itself; the whole module mirrors the calendar's live-ICS posture.

## Information architecture
- Mail is a destination inside the unified shell (`index.html`, press `3`). Frontend is the `window.MailView` module in `src/static/js/mail.js` (IIFE, lazy init on first entry via `MailView.enter()`).
- Layout: mailbox sidebar (list + add/edit modal `#mailboxModal`) and a live inbox list. Selected mailbox persisted to `localStorage` (`mail.selectedMailboxId`).
- **Click a message row** → reader modal (`#mailMessageModal`): full plain-text body via `GET .../messages/<uid>` — still `BODY.PEEK`, so opening never marks it read server-side. Footer "Add as task" hands off to the email-to-task flow.
- **Email → task in one gesture**: right-click a message row (or its `Task` button, or the reader's footer button) → `POST .../add-task` → shared `TaskDraftModal` pre-filled → confirm → `POST /api/tasks` → the shell's `loadTasks()` refreshes the board.

## Model (`Mailbox` in `src/models.py`)
`id, label, host, port (993), username, password_encrypted, use_ssl (True; False = plain IMAP + best-effort STARTTLS), space_id (FK, nullable), created_at, updated_at`. `to_dict()` exposes `has_password` and the denormalized space name — **never the password**.

## Credential security (invariants — do NOT weaken)
- Passwords are encrypted at rest with Fernet, key = sha256(SECRET_KEY) urlsafe-b64 (`src/crypto_utils.py`). A leaked `tasks.db` alone does not leak mailbox passwords.
- Plaintext exists in memory only for the duration of one IMAP call (`_mailbox_password()` inside the request handlers).
- No endpoint returns a password in any form. The edit modal sends a password ONLY when the user typed a new one; `PUT` ignores empty/absent password fields.
- SECRET_KEY rotation orphans stored passwords: message endpoints answer **409** with a re-enter message (`InvalidToken` catch), not a 500.

## Live IMAP fetch (`src/mail_integration.py`)
- stdlib `imaplib` + `email` only (no new heavy dependency; matches the project's lean-deps posture).
- `fetch_messages(host, port, username, password, use_ssl, limit)` → newest `limit` INBOX messages as transient DTOs `{uid, subject, from, date, snippet, unread}`. `fetch_message_body(..., uid)` → same DTO + full `body` (text/plain part, best effort).
- `BODY.PEEK[]` + `readonly=True` select — browsing never marks messages read.
- Encoded headers decoded via `email.header.decode_header`; snippets are whitespace-collapsed first 200 chars.

## Routes (`src/routes/mailboxes.py`, all `login_required`)
- `GET/POST /api/mailboxes`, `PUT/DELETE /api/mailboxes/<id>` — CRUD, audited (`entity_type='mailbox'`; to_dict has no secrets so audit rows are safe).
- `GET /api/mailboxes/<id>/messages?limit=` (capped at 100) — live fetch; IMAP failure → **502** with the error string.
- `GET /api/mailboxes/<id>/messages/<uid>` — one message incl. full `body` for the reader modal; 404 unknown uid, same 502/409 mapping.
- `POST /api/mailboxes/<id>/messages/<uid>/add-task` — fetches the body, builds `Config.EMAIL_TO_TASK_PROMPT + spaces_context()`, calls `email_to_task_with_ai`, pre-tags drafts with the mailbox's `space_id` when the LLM chose none, returns the drafts. **Persists nothing** (same contract as promote-to-task). Unknown uid → 404.

## AI seam
See `.opencode/context/topics/ai-parsing.md` § Email-to-task seam: reuses the `parse_task` provider method (no `complete()` generalization), dedicated prompt file `src/prompts/email_to_task.md`, graceful degradation to a subject/body draft.

## Testing (`tests/test_mail.py`)
IMAP patched at the route seam (`routes.mailboxes.fetch_messages` / `fetch_message_body` monkeypatched — NOT imaplib itself), AI via the shared `stub_ai_provider`. Covered: crypto roundtrip, encryption-at-rest + no-password-echo, credential validation (400), space relink keeps password, audited delete, canned-DTO fetch (decrypted password reaches the seam), message-body fetch (reader), draft pre-tagging + nothing-persisted, 404 unknown uid, 502 on IMAP failure.

## Out of scope (deliberate, PrePRD)
Send/reply/compose; IMAP background sync or push; persisting messages (and therefore server-side search); per-mailbox auth models.
