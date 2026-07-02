// Spaces view module for the unified workspace shell.
// Replaces the old header-button modal: full space management as a
// destination (press 5). The headline field is the AI context markdown —
// user-written guidance injected into every AI task prompt (guide, not
// source; the backend frames it so it's never copied into tasks).

window.SpacesView = (function () {

    const STORAGE_SPACE_KEY = 'spaces.selectedSpaceId';
    const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    const state = {
        initialized: false,
        spaces: [],
        selectedId: null,   // null with editor open = creating a new space
        creating: false,
    };

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function setIndicator(text) {
        document.getElementById('spaceSaveIndicator').textContent = text || '';
    }

    async function loadSpaces() {
        state.spaces = await (await fetch('/api/spaces')).json();
        renderList();
    }

    function renderList() {
        const container = document.getElementById('spacesList');
        if (state.spaces.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-map-marker-alt fa-2x mb-2"></i>
                    <p class="small">No spaces yet.<br>Create one to organize tasks, notes and mail.</p>
                </div>`;
            return;
        }
        container.innerHTML = '';
        for (const sp of state.spaces) {
            const row = document.createElement('div');
            row.className = 'space-row' + (sp.id === state.selectedId ? ' active' : '');
            const windows = (sp.time_constraints || []).length;
            row.innerHTML = `
                <div class="space-row-name">${escapeHtml(sp.name)}</div>
                <div class="space-row-meta">
                    ${sp.context_markdown ? '<span title="Has AI context"><i class="fas fa-robot"></i></span>' : ''}
                    ${windows ? `<span title="Time windows"><i class="fas fa-clock"></i> ${windows}</span>` : ''}
                </div>
            `;
            row.addEventListener('click', () => selectSpace(sp.id));
            container.appendChild(row);
        }
    }

    function selectSpace(id) {
        const sp = state.spaces.find(s => s.id === id);
        if (!sp) return;
        state.selectedId = id;
        state.creating = false;
        localStorage.setItem(STORAGE_SPACE_KEY, String(id));
        renderList();
        openEditor(sp);
    }

    function newSpace() {
        state.selectedId = null;
        state.creating = true;
        renderList();
        openEditor(null);
        document.getElementById('spaceEditName').focus();
    }

    function openEditor(space) {
        document.getElementById('spaceEditorEmpty').style.display = 'none';
        document.getElementById('spaceEditor').style.display = 'block';
        document.getElementById('spaceEditName').value = space ? space.name : '';
        document.getElementById('spaceEditDescription').value = space ? (space.description || '') : '';
        document.getElementById('spaceEditContext').value = space ? (space.context_markdown || '') : '';
        document.getElementById('spaceDeleteBtn').style.display = space ? '' : 'none';
        setIndicator('');

        const constraints = document.getElementById('spaceEditConstraints');
        constraints.innerHTML = '';
        for (const c of (space ? space.time_constraints || [] : [])) {
            constraints.appendChild(constraintRow(c));
        }
    }

    function constraintRow(c = null) {
        const div = document.createElement('div');
        div.className = 'time-constraint-item d-flex gap-2 mb-2';
        div.innerHTML = `
            <select class="form-select constraint-day" style="width: auto;">
                ${DAY_NAMES.map((day, i) =>
                    `<option value="${i}" ${c && c.day === i ? 'selected' : ''}>${day}</option>`).join('')}
            </select>
            <input type="time" class="form-control constraint-start" style="width: auto;" value="${c ? c.start : ''}">
            <input type="time" class="form-control constraint-end" style="width: auto;" value="${c ? c.end : ''}">
            <button class="btn btn-sm btn-outline-danger" title="Remove window"><i class="fas fa-times"></i></button>
        `;
        div.querySelector('button').addEventListener('click', () => div.remove());
        return div;
    }

    function collectConstraints() {
        const out = [];
        document.querySelectorAll('#spaceEditConstraints .time-constraint-item').forEach(item => {
            const start = item.querySelector('.constraint-start').value;
            const end = item.querySelector('.constraint-end').value;
            if (start && end) {
                out.push({ day: parseInt(item.querySelector('.constraint-day').value), start, end });
            }
        });
        return out;
    }

    async function saveSpace() {
        const name = document.getElementById('spaceEditName').value.trim();
        if (!name) {
            setIndicator('name is required');
            document.getElementById('spaceEditName').focus();
            return;
        }
        const body = {
            name,
            description: document.getElementById('spaceEditDescription').value.trim(),
            context_markdown: document.getElementById('spaceEditContext').value,
            time_constraints: collectConstraints(),
        };

        setIndicator('saving…');
        const resp = await fetch(
            state.selectedId ? `/api/spaces/${state.selectedId}` : '/api/spaces', {
                method: state.selectedId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            setIndicator(err.error || 'save failed');
            return;
        }
        const saved = await resp.json();
        state.selectedId = saved.id;
        state.creating = false;
        localStorage.setItem(STORAGE_SPACE_KEY, String(saved.id));
        await loadSpaces();
        setIndicator('saved');
        // Refresh the shell's space chips + selects everywhere.
        if (typeof window.loadSpaces === 'function') window.loadSpaces();
    }

    async function deleteSpace() {
        const sp = state.spaces.find(s => s.id === state.selectedId);
        if (!sp) return;
        if (!confirm(`Delete space "${sp.name}"? Its tasks, notes and mailboxes keep existing but lose the link.`)) return;

        await fetch(`/api/spaces/${sp.id}`, { method: 'DELETE' });
        state.selectedId = null;
        document.getElementById('spaceEditor').style.display = 'none';
        document.getElementById('spaceEditorEmpty').style.display = 'block';
        await loadSpaces();
        if (typeof window.loadSpaces === 'function') window.loadSpaces();
    }

    // --- Init ---

    async function enter() {
        if (!state.initialized) {
            state.initialized = true;
            document.getElementById('newSpaceBtn').addEventListener('click', newSpace);
            document.getElementById('spaceSaveBtn').addEventListener('click', saveSpace);
            document.getElementById('spaceDeleteBtn').addEventListener('click', deleteSpace);
            document.getElementById('spaceAddConstraintBtn').addEventListener('click', () => {
                document.getElementById('spaceEditConstraints').appendChild(constraintRow());
            });
            await loadSpaces();
            const saved = parseInt(localStorage.getItem(STORAGE_SPACE_KEY));
            if (saved && state.spaces.find(s => s.id === saved)) {
                selectSpace(saved);
            } else if (state.spaces.length > 0) {
                selectSpace(state.spaces[0].id);
            }
        } else {
            const current = state.selectedId;
            await loadSpaces();
            // The selected space may have been deleted elsewhere meanwhile.
            if (current && !state.spaces.find(s => s.id === current) && !state.creating) {
                state.selectedId = null;
                document.getElementById('spaceEditor').style.display = 'none';
                document.getElementById('spaceEditorEmpty').style.display = 'block';
            }
        }
    }

    return { enter };
})();
