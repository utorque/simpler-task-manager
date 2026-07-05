// Shared "confirm this AI task draft" modal.
// Used by the Notes promote-to-task flow and the Mail email-to-task flow:
// both routes return draft DTOs and persist nothing — the user confirms here
// and the task is created via the existing POST /api/tasks.

window.TaskDraftModal = (function () {

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function buildTaskForm(draft, spaces) {
        const spaceOptions = spaces.map(sp =>
            `<option value="${sp.id}" ${draft.space_id === sp.id ? 'selected' : ''}>${escapeHtml(sp.name)}</option>`
        ).join('');
        const deadlineVal = draft.deadline
            ? String(draft.deadline).replace(' ', 'T').slice(0, 16)
            : '';
        const subtaskRows = (draft.subtasks || []).map(s => {
            const title = typeof s === 'string' ? s : (s && s.title) || '';
            return subtaskRow(title);
        }).join('');
        return `
            <div class="mb-2">
                <label class="form-label small">Title</label>
                <input class="form-control form-control-sm" data-field="title" value="${escapeHtml(draft.title || '')}">
            </div>
            <div class="mb-2">
                <label class="form-label small d-flex justify-content-between align-items-center w-100">
                    Subtasks
                    <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-act="add-subtask" title="Add subtask">+</button>
                </label>
                <div data-role="subtasks">${subtaskRows}</div>
            </div>
            <div class="row g-2 mb-2">
                <div class="col">
                    <label class="form-label small">Priority (0–10)</label>
                    <input type="number" min="0" max="10" class="form-control form-control-sm" data-field="priority" value="${draft.priority ?? 0}">
                </div>
                <div class="col">
                    <label class="form-label small">Duration (min)</label>
                    <input type="number" min="1" class="form-control form-control-sm" data-field="estimated_duration" value="${draft.estimated_duration ?? 60}">
                </div>
            </div>
            <div class="mb-2">
                <label class="form-label small">Deadline</label>
                <input type="datetime-local" class="form-control form-control-sm" data-field="deadline" value="${deadlineVal}">
            </div>
            <div class="mb-2">
                <label class="form-label small">Space</label>
                <select class="form-select form-select-sm" data-field="space_id">${spaceOptions}</select>
            </div>
            <div class="mb-2">
                <label class="form-label small">Description</label>
                <textarea class="form-control form-control-sm" rows="3" data-field="description">${escapeHtml(draft.description || '')}</textarea>
            </div>
        `;
    }

    function subtaskRow(title) {
        return `
            <div class="d-flex align-items-center gap-1 mb-1" data-role="subtask-row">
                <input class="form-control form-control-sm" data-role="subtask-title" value="${escapeHtml(title)}">
                <button type="button" class="btn-close" style="font-size:.6rem" data-act="remove-subtask" aria-label="Remove subtask"></button>
            </div>`;
    }

    function readForm(modalEl) {
        const get = (f) => {
            const el = modalEl.querySelector(`[data-field="${f}"]`);
            return el ? el.value : '';
        };
        const subtasks = Array.from(
            modalEl.querySelectorAll('[data-role="subtask-title"]'))
            .map(el => el.value.trim())
            .filter(Boolean);
        return {
            title: get('title').trim(),
            description: get('description') || null,
            space_id: Number(get('space_id')) || null,
            priority: Number(get('priority')) || 0,
            estimated_duration: Number(get('estimated_duration')) || 60,
            deadline: get('deadline') || null,
            subtasks: subtasks,
        };
    }

    // Resolves with the created task, or null if the user cancelled.
    function confirmDraft(draft, spaces) {
        return new Promise((resolve) => {
            const backdrop = document.createElement('div');
            backdrop.className = 'promote-task-backdrop';
            backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:1080;';
            const card = document.createElement('div');
            card.className = 'promote-task-card';
            card.style.cssText = 'background:#fff;border-radius:.5rem;padding:1rem 1.25rem;width:min(520px,92vw);max-height:88vh;overflow:auto;';
            card.innerHTML = `
                <h6 class="mb-3">Confirm task</h6>
                <form>${buildTaskForm(draft, spaces)}</form>
                <div class="d-flex justify-content-end gap-2 mt-3">
                    <button type="button" class="btn btn-sm btn-secondary" data-act="cancel">Cancel</button>
                    <button type="button" class="btn btn-sm btn-primary" data-act="confirm">Create task</button>
                </div>
            `;
            backdrop.appendChild(card);
            document.body.appendChild(backdrop);

            const close = () => backdrop.remove();
            // Subtask row add/remove (rows are read back on confirm).
            card.addEventListener('click', (e) => {
                if (e.target.closest('[data-act="add-subtask"]')) {
                    const holder = card.querySelector('[data-role="subtasks"]');
                    holder.insertAdjacentHTML('beforeend', subtaskRow(''));
                    holder.lastElementChild.querySelector('input').focus();
                } else if (e.target.closest('[data-act="remove-subtask"]')) {
                    e.target.closest('[data-role="subtask-row"]').remove();
                }
            });
            card.querySelector('[data-act="cancel"]').addEventListener('click', () => { close(); resolve(null); });
            backdrop.addEventListener('click', (e) => { if (e.target === backdrop) { close(); resolve(null); } });
            card.querySelector('[data-act="confirm"]').addEventListener('click', async () => {
                const body = readForm(card);
                // Provenance passthrough: promote-to-task drafts carry the
                // source note's id (not a form field — never user-edited).
                if (draft.note_id != null) body.note_id = draft.note_id;
                // Note-linked drafts may stay untitled: the note-save
                // backfill names the task once the note gets a # title.
                if (!body.title && body.note_id == null) { alert('Title is required'); return; }
                const btn = card.querySelector('[data-act="confirm"]');
                btn.disabled = true;
                btn.textContent = 'Creating…';
                try {
                    const resp = await fetch('/api/tasks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    });
                    if (!resp.ok) {
                        const err = await resp.json().catch(() => ({}));
                        throw new Error(err.error || `HTTP ${resp.status}`);
                    }
                    close();
                    resolve(await resp.json());
                } catch (e) {
                    btn.disabled = false;
                    btn.textContent = 'Create task';
                    alert('Failed to create task: ' + e.message);
                }
            });
        });
    }

    // Confirm drafts in sequence; cancelling one stops the rest.
    // Resolves with the number of tasks created.
    async function confirmDrafts(drafts, spaces) {
        let created = 0;
        for (const draft of drafts) {
            const task = await confirmDraft(draft, spaces);
            if (!task) break;
            created += 1;
        }
        return created;
    }

    return { confirmDraft, confirmDrafts };
})();
