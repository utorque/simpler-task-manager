// Notes view module for the unified workspace shell.
// Everything is scoped inside an IIFE; the shell (app.js) calls
// NotesView.enter() when the user switches to the Notes destination.
// Init (EasyMDE, wiring, data load) is lazy — it happens on first entry.

window.NotesView = (function () {

    const STORAGE_SPACE_KEY = 'notes.selectedSpaceId';       // legacy single-space key (migrated)
    const STORAGE_SPACES_KEY = 'notes.selectedSpaceIds';     // JSON array, or 'all'
    const STORAGE_EXCLUDED_KEY = 'notes.excludedSpaceIds';   // JSON array
    const AUTOSAVE_DEBOUNCE_MS = 800;
    const CONTENT_PREVIEW_LEN = 80;

    const state = {
        initialized: false,
        spaces: [],
        // Same convention as the kanban board chips: null = all spaces,
        // otherwise a non-empty array of space ids (Ctrl+click multi-select).
        selectedSpaceIds: null,
        // Space ids muted from the list: Alt+click a chip greys it out and
        // hides its notes. Complements the include-filter above.
        excludedSpaceIds: new Set(),
        notes: [],
        // Ctrl+click download selection in the notes list (ids). Empty set =
        // no selection → the download button exports every note in view.
        selectedNoteIds: new Set(),
        currentNote: null,        // {id, ...} once persisted (POST issued); null until then
        editorDirty: false,
        saveTimer: null,
        lastCleaned: null,        // for single-step Undo Cleanify
    };

    let easyMDE = null;

    async function api(path, opts = {}) {
        const resp = await fetch(path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        if (resp.status === 204) return null;
        return resp.json();
    }

    function setSaveIndicator(text) {
        document.getElementById('saveIndicator').textContent = text || '';
    }

    // --- Spaces ---
    function restoreSelection() {
        const raw = localStorage.getItem(STORAGE_SPACES_KEY);
        if (raw === 'all') return null;
        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                const ids = parsed.filter(id => state.spaces.some(s => s.id === id));
                if (ids.length) return ids;
                return null;
            }
        } catch (e) { /* fall through to legacy key */ }
        // Legacy single-space dropdown selection.
        const legacy = Number(localStorage.getItem(STORAGE_SPACE_KEY));
        if (legacy && state.spaces.some(s => s.id === legacy)) return [legacy];
        return null;
    }

    function storeSelection() {
        localStorage.setItem(STORAGE_SPACES_KEY,
            state.selectedSpaceIds === null ? 'all' : JSON.stringify(state.selectedSpaceIds));
        localStorage.setItem(STORAGE_EXCLUDED_KEY,
            JSON.stringify(Array.from(state.excludedSpaceIds)));
    }

    function restoreExclusions() {
        try {
            const parsed = JSON.parse(localStorage.getItem(STORAGE_EXCLUDED_KEY));
            if (Array.isArray(parsed)) {
                return new Set(parsed.filter(id => state.spaces.some(s => s.id === id)));
            }
        } catch (e) { /* absent or corrupt → nothing excluded */ }
        return new Set();
    }

    async function loadSpaces() {
        state.spaces = await api('/api/spaces');
        state.selectedSpaceIds = restoreSelection();
        state.excludedSpaceIds = restoreExclusions();
        renderSpaceChips();
    }

    // The space ids the list actually shows: the include-filter (null = all)
    // minus the excluded set.
    function visibleSpaceIds() {
        const base = state.selectedSpaceIds !== null
            ? state.selectedSpaceIds
            : state.spaces.map(s => s.id);
        return base.filter(id => !state.excludedSpaceIds.has(id));
    }

    // Same chips as the kanban board: plain click = show only that space,
    // Ctrl+click = toggle the space in/out of the multi-space selection,
    // Alt+click = exclude the space (greyed chip, its notes hidden until
    // Alt+clicked again). "All" resets both filter and exclusions.
    function renderSpaceChips() {
        const container = document.getElementById('notesSpaceChips');
        const chip = (label, value, active, excluded) => `
            <button class="space-chip ${active ? 'active' : ''} ${excluded ? 'excluded' : ''}"
                    data-space-id="${value === null ? 'all' : value}">
                ${label}
            </button>`;
        container.innerHTML =
            chip('All', null, state.selectedSpaceIds === null && state.excludedSpaceIds.size === 0, false) +
            state.spaces.map(sp => chip(escapeHtml(sp.name), sp.id,
                state.selectedSpaceIds !== null && state.selectedSpaceIds.includes(sp.id),
                state.excludedSpaceIds.has(sp.id))).join('');

        container.querySelectorAll('.space-chip').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const v = btn.dataset.spaceId;
                if (v === 'all') {
                    state.selectedSpaceIds = null;
                    state.excludedSpaceIds.clear();
                } else {
                    const id = parseInt(v);
                    if (e.altKey) {
                        if (state.excludedSpaceIds.has(id)) {
                            state.excludedSpaceIds.delete(id);
                        } else {
                            state.excludedSpaceIds.add(id);
                            // An excluded space can't stay in the include set.
                            if (state.selectedSpaceIds !== null) {
                                state.selectedSpaceIds = state.selectedSpaceIds.filter(x => x !== id);
                                if (state.selectedSpaceIds.length === 0) state.selectedSpaceIds = null;
                            }
                        }
                    } else if (e.ctrlKey || e.metaKey) {
                        const set = new Set(state.selectedSpaceIds || []);
                        set.has(id) ? set.delete(id) : set.add(id);
                        state.selectedSpaceIds = set.size ? Array.from(set) : null;
                        state.excludedSpaceIds.delete(id); // explicitly picked → visible
                    } else {
                        state.selectedSpaceIds = [id];
                        state.excludedSpaceIds.delete(id); // explicitly picked → visible
                    }
                }
                storeSelection();
                renderSpaceChips();
                loadNotes();
            });
        });
    }

    // The space a NEW note lands in: the first visible (selected and not
    // excluded) space, falling back to the first space overall.
    function primarySpaceId() {
        const visible = visibleSpaceIds();
        if (visible.length) return visible[0];
        return state.spaces[0] && state.spaces[0].id;
    }

    function spaceName(spaceId) {
        const sp = state.spaces.find(s => s.id === spaceId);
        return sp ? sp.name : '';
    }

    // --- Notes list ---
    async function loadNotes() {
        if (state.selectedSpaceIds === null && state.excludedSpaceIds.size === 0) {
            // No restriction at all — one unfiltered fetch.
            state.notes = await api('/api/notes');
        } else {
            const ids = visibleSpaceIds();
            state.notes = ids.length === 0
                ? [] // every space filtered out or excluded
                : await api('/api/notes?' + ids.map(id => `space_id=${id}`).join('&'));
        }
        // Prune the download selection: keep only notes still in view.
        const visible = new Set(state.notes.map(n => n.id));
        state.selectedNoteIds = new Set([...state.selectedNoteIds].filter(id => visible.has(id)));
        renderList();
    }

    function relativeTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        const diff = (Date.now() - d.getTime()) / 1000;
        if (diff < 60) return 'just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }

    function previewContent(content) {
        if (!content) return '';
        const firstLine = content.split('\n').find(l => l.trim()) || '';
        return firstLine.length > CONTENT_PREVIEW_LEN
            ? firstLine.slice(0, CONTENT_PREVIEW_LEN) + '…'
            : firstLine;
    }

    function renderList() {
        const container = document.getElementById('notes-container');
        if (state.notes.length === 0) {
            container.innerHTML = `<div class="text-center text-muted py-5">
                <i class="fas fa-sticky-note fa-3x mb-3"></i>
                <p>No notes yet. Click + to capture a thought.</p>
            </div>`;
            updateDownloadButton();
            return;
        }
        container.innerHTML = '';
        // When viewing several spaces (or all), tag each note with its space.
        const showSpace = state.selectedSpaceIds === null || state.selectedSpaceIds.length > 1;
        for (const n of state.notes) {
            const title = n.title && n.title.trim() ? n.title : 'Untitled';
            const row = document.createElement('div');
            row.className = 'note-row';
            if (state.currentNote && state.currentNote.id === n.id) row.classList.add('active');
            if (state.selectedNoteIds.has(n.id)) row.classList.add('selected');
            row.innerHTML = `
                <div class="note-row-title">${escapeHtml(title)}
                    ${showSpace && spaceName(n.space_id) ? `<span class="note-row-space">${escapeHtml(spaceName(n.space_id))}</span>` : ''}
                </div>
                <div class="note-row-preview">${escapeHtml(previewContent(n.content_markdown))}</div>
                <div class="note-row-time">${relativeTime(n.updated_at)}</div>
            `;
            // Ctrl+click = toggle the note in/out of the download selection;
            // plain click = open it (selection untouched, Esc clears it).
            row.addEventListener('click', (e) => {
                if (e.ctrlKey || e.metaKey) {
                    state.selectedNoteIds.has(n.id)
                        ? state.selectedNoteIds.delete(n.id)
                        : state.selectedNoteIds.add(n.id);
                    renderList();
                } else {
                    openNote(n);
                }
            });
            container.appendChild(row);
        }
        updateDownloadButton();
    }

    function updateDownloadButton() {
        const label = document.getElementById('downloadNotesLabel');
        const btn = document.getElementById('downloadNotesBtn');
        const count = state.selectedNoteIds.size;
        label.textContent = count ? `Download ${count} selected` : 'Download';
        btn.disabled = state.notes.length === 0;
    }

    // --- Download (selected notes, or every note in view) ---
    function notesToMarkdown(notes) {
        return notes.map(n => {
            const title = n.title && n.title.trim() ? n.title.trim() : 'Untitled';
            const content = (n.content_markdown || '').trim();
            // Skip the heading when the note body already starts with one
            // (e.g. a cleanified note leads with its own `# Title`).
            const heading = content.startsWith('# ') ? '' : `# ${title}\n\n`;
            return heading + content;
        }).join('\n\n---\n\n') + '\n';
    }

    function downloadNotes() {
        const selected = state.selectedNoteIds.size
            ? state.notes.filter(n => state.selectedNoteIds.has(n.id))
            : state.notes;
        if (!selected.length) return;
        const blob = new Blob([notesToMarkdown(selected)], { type: 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `notes-${new Date().toISOString().slice(0, 10)}.md`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    }

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    // --- Editor ---
    // Notes open rendered (EasyMDE preview mode) by default; clicking the
    // preview switches to edit mode. Empty notes go straight to edit — an
    // empty preview pane is a dead end.
    function setPreviewMode(on) {
        if (!easyMDE) return;
        if (easyMDE.isPreviewActive() !== on) easyMDE.togglePreview();
    }

    function clearEditor() {
        state.currentNote = null;
        state.editorDirty = false;
        state.lastCleaned = null;
        document.getElementById('noteTitle').value = '';
        setPreviewMode(false);
        if (easyMDE) easyMDE.value('');
        setSaveIndicator('');
        setActiveButtonsDisabledState();
    }

    function openNote(note) {
        cancelPendingSave();
        state.currentNote = { ...note };
        state.lastCleaned = null;
        document.getElementById('noteTitle').value = note.title || '';
        // Load the content with preview off (the preview pane only re-renders
        // on toggle), then flip preview on for non-empty notes.
        setPreviewMode(false);
        if (easyMDE) easyMDE.value(note.content_markdown || '');
        setPreviewMode(!!(note.content_markdown || '').trim());
        state.editorDirty = false;
        setSaveIndicator('');
        renderList();
        setActiveButtonsDisabledState();
    }

    function newNote() {
        clearEditor();
        document.getElementById('noteTitle').focus();
    }

    function hasNonEmptyContent() {
        const title = document.getElementById('noteTitle').value.trim();
        const content = (easyMDE ? easyMDE.value() : '').trim();
        return title !== '' || content !== '';
    }

    function scheduleSave() {
        cancelPendingSave();
        setSaveIndicator('saving…');
        state.saveTimer = setTimeout(flushSave, AUTOSAVE_DEBOUNCE_MS);
    }

    function cancelPendingSave() {
        if (state.saveTimer) {
            clearTimeout(state.saveTimer);
            state.saveTimer = null;
        }
    }

    async function flushSave() {
        state.saveTimer = null;
        if (!hasNonEmptyContent()) {
            // Deferred persistence: nothing to persist yet.
            setSaveIndicator('');
            return;
        }
        const title = document.getElementById('noteTitle').value;
        const content = easyMDE ? easyMDE.value() : '';
        try {
            if (!state.currentNote) {
                const created = await api('/api/notes', {
                    method: 'POST',
                    body: JSON.stringify({
                        space_id: primarySpaceId(),
                        title,
                        content_markdown: content,
                    }),
                });
                state.currentNote = created;
                await loadNotes();
            } else {
                const updated = await api(`/api/notes/${state.currentNote.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ title, content_markdown: content }),
                });
                state.currentNote = updated;
                await loadNotes();
            }
            setSaveIndicator('saved');
        } catch (e) {
            setSaveIndicator('save failed');
        }
    }

    // beforeunload: if editor has non-empty content and no POST yet, the
    // debounced save may not have fired — flush it. If both title and content
    // are empty and no POST issued, nothing persists (deferred persistence).
    window.addEventListener('beforeunload', () => {
        if (state.initialized && hasNonEmptyContent() && state.saveTimer) {
            // Best-effort synchronous send; browsers may or may not complete it.
            flushSave();
        }
    });

    function setActiveButtonsDisabledState() {
        const hasNote = !!state.currentNote;
        const hasSelection = easyMDE && easyMDE.codemirror && easyMDE.codemirror.somethingSelected();
        document.getElementById('cleanifyBtn').disabled = !hasNote;
        document.getElementById('undoCleanifyBtn').disabled = !(hasNote && state.lastCleaned !== null);
        document.getElementById('notePromoteBtn').disabled = !(hasNote && hasSelection);
        document.getElementById('deleteNoteBtn').disabled = !hasNote;
    }

    async function cleanifyCurrentNote() {
        if (!state.currentNote) return;
        const btn = document.getElementById('cleanifyBtn');
        btn.disabled = true;
        setSaveIndicator('cleanifying…');
        try {
            const resp = await api(`/api/notes/${state.currentNote.id}/cleanify`, { method: 'POST' });
            if (!resp || typeof resp.content !== 'string') {
                setSaveIndicator('cleanify failed');
                return;
            }
            // Store the current editor content for single-step Undo BEFORE replacing.
            state.lastCleaned = easyMDE ? easyMDE.value() : '';
            replaceEditorContent(resp.content);
            // easyMDE.value() fires the CM5 `change` event → scheduleSave() debounced PUT.
            setSaveIndicator('cleanified');
        } catch (e) {
            setSaveIndicator('cleanify failed');
        } finally {
            setActiveButtonsDisabledState();
        }
    }

    // Replace the editor buffer, keeping an active preview in sync (the
    // preview pane only re-renders on toggle, so flip it around the write).
    function replaceEditorContent(content) {
        const wasPreview = easyMDE.isPreviewActive();
        if (wasPreview) easyMDE.togglePreview();
        easyMDE.value(content);
        if (wasPreview) easyMDE.togglePreview();
    }

    function undoCleanify() {
        if (state.lastCleaned === null) return;
        const previous = state.lastCleaned;
        state.lastCleaned = null;
        replaceEditorContent(previous);
        // easyMDE.value() fires the CM5 `change` event → scheduleSave() debounced PUT.
        setSaveIndicator('restored');
        setActiveButtonsDisabledState();
    }

    async function deleteCurrentNote() {
        if (!state.currentNote) return;
        if (!confirm('Delete this note?')) return;
        await api(`/api/notes/${state.currentNote.id}`, { method: 'DELETE' });
        state.currentNote = null;
        await loadNotes();
        clearEditor();
    }

    // --- Promote-to-task ---
    // The promote route returns draft DTOs and persists nothing; the shared
    // TaskDraftModal confirms them and creates via POST /api/tasks. The
    // note's content is never touched.

    async function promoteSelectionToTask() {
        if (!state.currentNote || !easyMDE) return;
        const sel = easyMDE.codemirror.getSelection();
        if (!sel || !sel.trim()) return; // button should already be disabled; guard anyway

        const btn = document.getElementById('notePromoteBtn');
        const origDisabled = btn.disabled;
        btn.disabled = true;
        setSaveIndicator('promoting…');
        try {
            const resp = await fetch(`/api/notes/${state.currentNote.id}/promote-to-task`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ selected_text: sel }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${resp.status}`);
            }
            const drafts = await resp.json();
            if (!Array.isArray(drafts) || drafts.length === 0) {
                setSaveIndicator('no task drafted');
                return;
            }
            // Confirm each draft in sequence (cancel stops the rest).
            const created = await window.TaskDraftModal.confirmDrafts(drafts, state.spaces);
            setSaveIndicator(created ? 'task created' : '');
            if (created && typeof window.loadTasks === 'function') window.loadTasks();
        } catch (e) {
            alert('Promote to task failed: ' + e.message);
            setSaveIndicator('promote failed');
        } finally {
            btn.disabled = origDisabled;
            setActiveButtonsDisabledState();
        }
    }

    // --- Init ---
    function initEditor() {
        const textarea = document.getElementById('noteEditor');
        easyMDE = new EasyMDE({
            element: textarea,
            autosave: { enabled: false },
            status: false,
            spellChecker: true,
            // Side-by-side must stay inside the notes layout, not take over
            // the whole screen (EasyMDE defaults to fullscreen side-by-side).
            sideBySideFullscreen: false,
            toolbar: [
                'bold', 'italic', 'strikethrough', '|',
                'heading-1', 'heading-2', 'heading-3', '|',
                'quote', 'unordered-list', 'ordered-list', '|',
                'code', 'horizontal-rule', '|',
                'link', 'image', '|',
                'preview', 'side-by-side', '|',
                { name: 'add-task', action: promoteSelectionToTask,
                  className: 'fa fa-plus-square', title: 'Add as task' },
                { name: 'cleanify', action: cleanifyCurrentNote,
                  className: 'fa fa-broom', title: 'Cleanify' },
                { name: 'undo-cleanify', action: undoCleanify,
                  className: 'fa fa-undo', title: 'Undo Cleanify' },
                '|', 'guide',
            ],
        });
        easyMDE.codemirror.on('change', () => {
            state.editorDirty = true;
            scheduleSave();
            setActiveButtonsDisabledState();
        });
        // Pure cursor moves (no content edit) also change selection state.
        easyMDE.codemirror.on('cursorActivity', () => {
            const btn = document.getElementById('notePromoteBtn');
            btn.disabled = !(state.currentNote && easyMDE.codemirror.somethingSelected());
        });
        // Preview → edit: clicking anywhere on the rendered note switches
        // back to the editor. Links keep their normal behavior, and the
        // side-by-side live preview (.editor-preview-side) is not affected.
        document.getElementById('view-notes').addEventListener('click', (e) => {
            if (!easyMDE.isPreviewActive()) return;
            if (e.target.closest('a')) return;
            if (!e.target.closest('.editor-preview-full')) return;
            setPreviewMode(false);
            easyMDE.codemirror.refresh();
            easyMDE.codemirror.focus();
        });
    }

    function initWiring() {
        document.getElementById('newNoteBtn').addEventListener('click', newNote);
        document.getElementById('downloadNotesBtn').addEventListener('click', downloadNotes);
        // Esc clears the download selection (only when Notes is the visible
        // destination and the user is not typing somewhere).
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || !state.selectedNoteIds.size) return;
            if (document.getElementById('view-notes').style.display === 'none') return;
            const t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            state.selectedNoteIds.clear();
            renderList();
        });
        document.getElementById('noteTitle').addEventListener('input', scheduleSave);
        document.getElementById('cleanifyBtn').addEventListener('click', cleanifyCurrentNote);
        document.getElementById('undoCleanifyBtn').addEventListener('click', undoCleanify);
        document.getElementById('deleteNoteBtn').addEventListener('click', deleteCurrentNote);
        document.getElementById('notePromoteBtn').addEventListener('click', promoteSelectionToTask);
    }

    // Immediate save (Ctrl+Enter): flush the debounced autosave right now.
    function saveNow() {
        cancelPendingSave();
        flushSave();
    }

    async function enter() {
        if (!state.initialized) {
            state.initialized = true;
            initEditor();
            initWiring();
            await loadSpaces();
            await loadNotes();
            clearEditor();
        } else {
            // Space list may have changed while we were away; loadSpaces
            // re-validates the stored selection against the fresh list.
            await loadSpaces();
            await loadNotes();
        }
        // CodeMirror mis-measures when initialized while hidden.
        if (easyMDE) easyMDE.codemirror.refresh();
    }

    // Open a specific note from outside the Notes view (task → source-note
    // jump). Ensures the view is initialized and loaded; falls back to a
    // direct fetch when the note is filtered out of the current space
    // selection. Returns true when the note was opened.
    async function openNoteById(noteId) {
        await enter();
        let note = state.notes.find(n => n.id === noteId);
        if (!note) {
            try {
                note = await api(`/api/notes/${noteId}`);
            } catch (e) {
                note = null; // 404 body isn't JSON → treat as not found
            }
        }
        if (!note || !note.id) return false;
        openNote(note);
        return true;
    }

    return { enter, saveNow, openNoteById };
})();
