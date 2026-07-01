// Mail view module for the unified workspace shell.
// Mailboxes are registered per Space; messages are fetched live via IMAP on
// each open (nothing persisted). "Add task" on a message asks the server for
// an AI task draft pre-tagged with the mailbox's Space, then confirms it via
// the shared TaskDraftModal — the fastest path from email to board.

window.MailView = (function () {

    const STORAGE_MAILBOX_KEY = 'mail.selectedMailboxId';

    const state = {
        initialized: false,
        mailboxes: [],
        spaces: [],
        selectedMailboxId: null,
        messages: [],
    };

    let mailboxModal = null;

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function setStatus(text) {
        document.getElementById('mailStatus').textContent = text || '';
    }

    async function loadSpaces() {
        state.spaces = await (await fetch('/api/spaces')).json();
    }

    async function loadMailboxes() {
        state.mailboxes = await (await fetch('/api/mailboxes')).json();
        renderMailboxList();
    }

    function renderMailboxList() {
        const container = document.getElementById('mailboxList');
        if (state.mailboxes.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-envelope-open fa-2x mb-2"></i>
                    <p class="small">No mailboxes yet.<br>Add one to triage email into tasks.</p>
                </div>`;
            return;
        }
        container.innerHTML = '';
        for (const mb of state.mailboxes) {
            const row = document.createElement('div');
            row.className = 'mailbox-row' + (mb.id === state.selectedMailboxId ? ' active' : '');
            row.innerHTML = `
                <div class="mailbox-row-main">
                    <div class="mailbox-row-label">${escapeHtml(mb.label)}</div>
                    <div class="mailbox-row-meta">
                        ${mb.space ? `<span class="task-space">${escapeHtml(mb.space)}</span>` : ''}
                        <span>${escapeHtml(mb.username)}</span>
                    </div>
                </div>
                <div class="mailbox-row-actions">
                    <button class="btn btn-sm app-action-btn" data-act="edit" title="Edit mailbox"><i class="fas fa-pen"></i></button>
                    <button class="btn btn-sm app-action-btn" data-act="delete" title="Delete mailbox"><i class="fas fa-trash"></i></button>
                </div>
            `;
            row.addEventListener('click', (e) => {
                const act = e.target.closest('[data-act]');
                if (act && act.dataset.act === 'edit') { openMailboxModal(mb); return; }
                if (act && act.dataset.act === 'delete') { deleteMailbox(mb); return; }
                selectMailbox(mb.id);
            });
            container.appendChild(row);
        }
    }

    async function selectMailbox(id) {
        state.selectedMailboxId = id;
        localStorage.setItem(STORAGE_MAILBOX_KEY, String(id));
        renderMailboxList();
        await loadMessages();
    }

    async function loadMessages() {
        const container = document.getElementById('mailMessages');
        if (!state.selectedMailboxId) {
            container.innerHTML = '';
            return;
        }
        setStatus('fetching…');
        container.innerHTML = '<div class="text-center text-muted py-5"><span class="loading"></span></div>';
        const resp = await fetch(`/api/mailboxes/${state.selectedMailboxId}/messages`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            setStatus('');
            container.innerHTML = `<div class="alert alert-warning m-3">${escapeHtml(err.error || 'Could not fetch messages')}</div>`;
            return;
        }
        state.messages = await resp.json();
        setStatus(`${state.messages.length} message${state.messages.length !== 1 ? 's' : ''}`);
        renderMessages();
    }

    function renderMessages() {
        const container = document.getElementById('mailMessages');
        if (state.messages.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="fas fa-inbox fa-2x mb-2"></i>
                    <p>Inbox is empty.</p>
                </div>`;
            return;
        }
        container.innerHTML = '';
        for (const msg of state.messages) {
            const row = document.createElement('div');
            row.className = 'mail-message-row' + (msg.unread ? ' unread' : '');
            row.innerHTML = `
                <div class="mail-message-main">
                    <div class="mail-message-subject">${escapeHtml(msg.subject || '(no subject)')}</div>
                    <div class="mail-message-snippet">${escapeHtml(msg.snippet || '')}</div>
                </div>
                <div class="mail-message-side">
                    <div class="mail-message-from">${escapeHtml(msg.from)}</div>
                    <div class="mail-message-date">${escapeHtml(msg.date)}</div>
                </div>
                <button class="btn btn-sm btn-outline-primary mail-add-task" title="Add task from this email (or right-click the row)">
                    <i class="fas fa-plus-square"></i> Task
                </button>
            `;
            row.querySelector('.mail-add-task').addEventListener('click', () => addTaskFromMessage(msg));
            // Right-click = "Add task" (PrePRD story 37), same action as the button.
            row.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                addTaskFromMessage(msg);
            });
            container.appendChild(row);
        }
    }

    async function addTaskFromMessage(msg) {
        setStatus('drafting task…');
        const resp = await fetch(
            `/api/mailboxes/${state.selectedMailboxId}/messages/${encodeURIComponent(msg.uid)}/add-task`,
            { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            setStatus('');
            alert(err.error || 'Could not draft a task from this email');
            return;
        }
        const drafts = await resp.json();
        const created = await window.TaskDraftModal.confirmDrafts(drafts, state.spaces);
        setStatus(created ? `${created} task${created > 1 ? 's' : ''} created` : '');
        // Refresh the board so the new task shows up immediately.
        if (created && typeof window.loadTasks === 'function') window.loadTasks();
    }

    // --- Mailbox add/edit modal ---

    function openMailboxModal(mailbox = null) {
        document.getElementById('mailboxModalTitle').textContent =
            mailbox ? `Edit ${mailbox.label}` : 'Add Mailbox';
        document.getElementById('mailboxId').value = mailbox ? mailbox.id : '';
        document.getElementById('mailboxLabel').value = mailbox ? mailbox.label : '';
        document.getElementById('mailboxHost').value = mailbox ? mailbox.host : '';
        document.getElementById('mailboxPort').value = mailbox ? mailbox.port : 993;
        document.getElementById('mailboxUsername').value = mailbox ? mailbox.username : '';
        document.getElementById('mailboxPassword').value = '';
        document.getElementById('mailboxPassword').placeholder =
            mailbox && mailbox.has_password ? '(unchanged)' : 'App password';
        document.getElementById('mailboxSsl').checked = mailbox ? mailbox.use_ssl : true;

        const spaceSel = document.getElementById('mailboxSpace');
        spaceSel.innerHTML = '<option value="">None</option>' + state.spaces.map(sp =>
            `<option value="${sp.id}" ${mailbox && mailbox.space_id === sp.id ? 'selected' : ''}>${escapeHtml(sp.name)}</option>`
        ).join('');

        mailboxModal.show();
    }

    async function saveMailbox() {
        const id = document.getElementById('mailboxId').value;
        const body = {
            label: document.getElementById('mailboxLabel').value.trim(),
            host: document.getElementById('mailboxHost').value.trim(),
            port: parseInt(document.getElementById('mailboxPort').value) || 993,
            username: document.getElementById('mailboxUsername').value.trim(),
            use_ssl: document.getElementById('mailboxSsl').checked,
            space_id: document.getElementById('mailboxSpace').value
                ? parseInt(document.getElementById('mailboxSpace').value) : null,
        };
        const password = document.getElementById('mailboxPassword').value;
        if (password) body.password = password;

        const resp = await fetch(id ? `/api/mailboxes/${id}` : '/api/mailboxes', {
            method: id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            alert(err.error || 'Could not save mailbox');
            return;
        }
        mailboxModal.hide();
        await loadMailboxes();
    }

    async function deleteMailbox(mailbox) {
        if (!confirm(`Delete mailbox "${mailbox.label}"? (No emails are stored — this only removes the registration.)`)) return;
        await fetch(`/api/mailboxes/${mailbox.id}`, { method: 'DELETE' });
        if (state.selectedMailboxId === mailbox.id) {
            state.selectedMailboxId = null;
            document.getElementById('mailMessages').innerHTML = '';
            setStatus('');
        }
        await loadMailboxes();
    }

    // --- Init ---

    async function enter() {
        if (!state.initialized) {
            state.initialized = true;
            mailboxModal = new bootstrap.Modal(document.getElementById('mailboxModal'));
            document.getElementById('addMailboxBtn').addEventListener('click', () => openMailboxModal());
            document.getElementById('saveMailboxBtn').addEventListener('click', saveMailbox);
            document.getElementById('refreshMailBtn').addEventListener('click', loadMessages);
            await loadSpaces();
            await loadMailboxes();
            const saved = parseInt(localStorage.getItem(STORAGE_MAILBOX_KEY));
            if (saved && state.mailboxes.find(m => m.id === saved)) {
                await selectMailbox(saved);
            } else if (state.mailboxes.length === 1) {
                await selectMailbox(state.mailboxes[0].id);
            }
        } else {
            await loadSpaces();
            await loadMailboxes();
        }
    }

    return { enter };
})();
