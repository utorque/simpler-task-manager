// ===== Unified ADHD-friendly workspace shell =====
// One header, four destinations (Tasks / Calendar / Notes [/ Mail]), one
// global quick-capture input. Tasks = kanban board (home) + grouped-by-space
// overview (secondary). Calendar behavior is preserved as-is.

// Global state
let tasks = [];
let spaces = [];
let calendar;
let taskModal;
let calendarModal;
let addTaskModal;
let helpModal;
let autoDoingModal;
let sortable;
let showCompletedTasks = false;
let overviewShowDone = localStorage.getItem('overviewShowDone') === 'true';
let focusedSpace = localStorage.getItem('focusedSpace') || null;
let currentDestination = null;
let tasksSubview = localStorage.getItem('tasksSubview') || 'board';
// null = all spaces; otherwise a non-empty array of space ids. Plain click on
// a chip selects that one space; Ctrl+click toggles it in/out of the set.
let boardSpaceFilter = parseStoredSpaceFilter();
// Space ids muted from the board: Alt+click a chip greys it out and hides its
// tasks. Complements the include-filter above (both persisted); "All spaces"
// resets both.
let boardExcludedSpaces = parseStoredExcludedSpaces();

// Multi-selection (kanban board only). Alt+click toggles a card in/out of
// this set; dragging a selected card moves the whole set; Enter forces all
// selected to done; Ctrl+C copies them as markdown bullets.
let selectedTaskIds = new Set();

const TASK_STATUSES = ['todo', 'doing', 'blocked', 'done'];
const DONE_COLUMN_LIMIT = 30;

function parseStoredSpaceFilter() {
    const raw = localStorage.getItem('boardSpaceFilter');
    if (raw === null || raw === 'all') return null;
    try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            const ids = parsed.filter(Number.isInteger);
            return ids.length ? ids : null;
        }
        if (Number.isInteger(parsed)) return [parsed]; // legacy single-id format
    } catch (e) { /* legacy non-JSON value falls through */ }
    const n = parseInt(raw);
    return Number.isNaN(n) ? null : [n];
}

function storeSpaceFilter() {
    localStorage.setItem('boardSpaceFilter',
        boardSpaceFilter === null ? 'all' : JSON.stringify(boardSpaceFilter));
}

function parseStoredExcludedSpaces() {
    try {
        const parsed = JSON.parse(localStorage.getItem('boardExcludedSpaces'));
        if (Array.isArray(parsed)) return new Set(parsed.filter(Number.isInteger));
    } catch (e) { /* absent or corrupt → nothing excluded */ }
    return new Set();
}

function storeExcludedSpaces() {
    localStorage.setItem('boardExcludedSpaces',
        JSON.stringify(Array.from(boardExcludedSpaces)));
}

// The space ids the board actually shows once the exclusions are applied:
// null = no restriction, otherwise a (possibly empty) array of ids. Used for
// the request scopes that must match what the user sees (auto-doing, inline
// add's restrict_space) — the board itself filters tasks directly.
function effectiveBoardSpaceIds() {
    if (boardExcludedSpaces.size === 0) return boardSpaceFilter;
    const base = boardSpaceFilter !== null ? boardSpaceFilter : spaces.map(s => s.id);
    return base.filter(id => !boardExcludedSpaces.has(id));
}

// Initialize app
document.addEventListener('DOMContentLoaded', async function() {
    // Initialize modals
    taskModal = new bootstrap.Modal(document.getElementById('taskModal'));
    calendarModal = new bootstrap.Modal(document.getElementById('calendarModal'));
    addTaskModal = new bootstrap.Modal(document.getElementById('addTaskModal'));
    helpModal = new bootstrap.Modal(document.getElementById('helpModal'));
    autoDoingModal = new bootstrap.Modal(document.getElementById('autoDoingModal'));

    // Initialize calendar
    initCalendar();

    // Initialize sortables (calendar sidebar list + kanban columns)
    initSortable();
    initBoardSortables();
    initBoardInlineAdd();

    // Load initial data
    await Promise.all([loadTasks(), loadSpaces()]);

    // Destination: deep link (#tasks/#notes/#mail/#calendar/#spaces/#assistant) > last used > Tasks.
    // Assistant only exists when the Chainlit app is mounted (tab + view are
    // server-side conditional) — an unavailable remembered/hashed destination
    // falls back to Tasks.
    const destinations = ['tasks', 'notes', 'mail', 'calendar', 'spaces'];
    if (document.getElementById('view-assistant')) destinations.push('assistant');
    const fromHash = window.location.hash.replace('#', '');
    let initial = destinations.includes(fromHash)
        ? fromHash
        : (localStorage.getItem('destination') || 'tasks');
    if (!destinations.includes(initial)) initial = 'tasks';
    switchDestination(initial);
    switchTasksSubview(tasksSubview);

    // Top-nav wiring
    document.querySelectorAll('#appNav .nav-tab').forEach(btn => {
        btn.addEventListener('click', () => switchDestination(btn.dataset.destination));
    });

    // Event listeners
    document.getElementById('parseTaskBtn').addEventListener('click', parseTask);
    document.getElementById('scheduleBtn').addEventListener('click', autoSchedule);
    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('addCalendarBtn').addEventListener('click', showCalendarModal);
    document.getElementById('helpBtn').addEventListener('click', () => helpModal.show());
    document.getElementById('saveTaskBtn').addEventListener('click', saveTask);
    document.getElementById('deleteTaskBtn').addEventListener('click', deleteTask);
    wireModalSubtasks();
    document.getElementById('editNoteLink').addEventListener('click', (e) => {
        e.preventDefault();
        const taskId = parseInt(document.getElementById('editTaskId').value);
        hideModalSafely(taskModal, 'taskModal');
        openTaskSourceNote(taskId);
    });
    document.getElementById('saveCalendarBtn').addEventListener('click', saveCalendar);
    document.getElementById('createTaskFromModalBtn').addEventListener('click', createTaskFromModal);

    // Task interactions share one convention everywhere:
    // click = edit, Ctrl+click = done, Shift+click = freeze, Alt+click = select.
    // Board-card exception: Shift+click advances the status instead of
    // freezing (cycleTaskStatus).
    wireTaskClickDelegation('taskList', '.task-item');
    wireTaskClickDelegation('spaceCardsContainer', '.space-task-item');
    wireTaskClickDelegation('boardView', '.board-card');
    wireTaskClickDelegation('overviewDoneList', '.task-item');

    // Clicking empty space inside the board clears the multi-selection.
    const boardViewEl = document.getElementById('boardView');
    if (boardViewEl) {
        boardViewEl.addEventListener('click', (e) => {
            if (!e.target.closest('.board-card') && selectedTaskIds.size > 0) {
                clearSelection();
            }
        });
    }

    // Enter submits the quick capture (single-line input; no newline needed)
    document.getElementById('quickCapture').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            parseTask();
        } else if (e.key === 'Escape') {
            this.blur();
        }
    });

    // Auto-focus on add task modal when shown
    document.getElementById('addTaskModal').addEventListener('shown.bs.modal', function() {
        document.getElementById('addTaskInput').focus();
    });

    // Auto-select doing: magic button in the Doing column header opens the
    // "what do you want to do?" modal; AI moves the matching to-dos to Doing.
    document.getElementById('autoDoingBtn').addEventListener('click', () => {
        document.getElementById('autoDoingInput').value = '';
        autoDoingModal.show();
    });
    document.getElementById('autoDoingModal').addEventListener('shown.bs.modal', function() {
        document.getElementById('autoDoingInput').focus();
    });
    document.getElementById('autoDoingSubmitBtn').addEventListener('click', autoSelectDoing);
    document.getElementById('autoDoingInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            autoSelectDoing();
        }
    });

    initKeyboardShortcuts();
    initGlobalCtrlEnterSave();
});

// ===== Destination switching (one header, N views) =====

function switchDestination(destination) {
    if (currentDestination === destination) return;
    clearSelection();
    currentDestination = destination;

    document.querySelectorAll('.app-view').forEach(v => v.style.display = 'none');
    const view = document.getElementById(`view-${destination}`);
    // The assistant view is a column flexbox (toolbar above the iframe).
    if (view) view.style.display = destination === 'assistant' ? 'flex' : 'block';

    document.querySelectorAll('#appNav .nav-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.destination === destination);
    });

    localStorage.setItem('destination', destination);
    history.replaceState(null, '', `#${destination}`);

    if (destination === 'calendar' && calendar) {
        // FullCalendar sizes wrong when rendered while hidden.
        calendar.updateSize();
    }
    if (destination === 'tasks') {
        renderTasksView();
    }
    if (destination === 'notes' && window.NotesView) {
        window.NotesView.enter();
    }
    if (destination === 'mail' && window.MailView) {
        window.MailView.enter();
    }
    if (destination === 'spaces' && window.SpacesView) {
        window.SpacesView.enter();
    }
    if (destination === 'assistant') {
        // Lazy-load the embedded assistant on first visit only.
        const frame = document.getElementById('assistantFrame');
        if (frame && !frame.src) frame.src = frame.dataset.src;
        renderAssistantSpaceChips();
    }
}

// Board <-> Overview toggle inside the Tasks destination (persisted)
function switchTasksSubview(subview) {
    clearSelection();
    tasksSubview = subview;
    localStorage.setItem('tasksSubview', subview);

    document.getElementById('boardView').style.display = subview === 'board' ? 'flex' : 'none';
    document.getElementById('overviewView').style.display = subview === 'overview' ? 'block' : 'none';
    document.getElementById('boardTab').classList.toggle('active', subview === 'board');
    document.getElementById('overviewTab').classList.toggle('active', subview === 'overview');

    renderTasksView();
}

function renderTasksView() {
    renderSpaceChips();
    if (tasksSubview === 'overview') {
        renderOverview();
    } else {
        renderBoard();
    }
}

// ===== Keyboard shortcuts =====

function isTypingContext(el) {
    if (!el) return false;
    return el.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) ||
        (el.closest && el.closest('.CodeMirror'));
}

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd+C: copy the selected tasks as markdown bullets (board only).
        if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
            if (tasksSubview === 'board' && selectedTaskIds.size > 0
                && !isTypingContext(e.target) && !document.querySelector('.modal.show')) {
                e.preventDefault();
                copySelectedAsMarkdown();
            }
            return;
        }

        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (isTypingContext(e.target)) return;
        if (document.querySelector('.modal.show')) return;

        // Enter: force every selected board task to done.
        if (e.key === 'Enter') {
            if (tasksSubview === 'board' && selectedTaskIds.size > 0) {
                e.preventDefault();
                markSelectedDone();
            }
            return;
        }

        // Escape: clear the current multi-selection.
        if (e.key === 'Escape') {
            if (selectedTaskIds.size > 0) clearSelection();
            return;
        }

        switch (e.key) {
            case '1': switchDestination('tasks'); break;
            case '2': switchDestination('notes'); break;
            case '3': switchDestination('mail'); break;
            case '4': switchDestination('calendar'); break;
            case '5': switchDestination('spaces'); break;
            case '6':
                if (document.getElementById('view-assistant')) switchDestination('assistant');
                break;
            case '/':
                e.preventDefault();
                document.getElementById('quickCapture').focus();
                break;
            case 's':
            case 'S':
                autoSchedule();
                break;
            case '?':
                helpModal.show();
                break;
        }
    });
}

// Global Ctrl+Enter = save, from any text input in the app. Capture phase so
// it wins over per-widget handlers (CodeMirror included); when a context is
// handled we stopPropagation so nothing double-fires.
function initGlobalCtrlEnterSave() {
    document.addEventListener('keydown', (e) => {
        if (!(e.ctrlKey || e.metaKey) || e.key !== 'Enter') return;
        if (!isTypingContext(e.target)) return;

        // 1) Inside an open modal: the footer's primary button IS the save
        // action (task edit, add-task, calendars, mailbox, auto-doing,
        // task-draft confirm…).
        const modal = e.target.closest('.modal.show') || document.querySelector('.modal.show');
        if (modal) {
            const btn = modal.querySelector('.modal-footer .btn-primary');
            if (btn && !btn.disabled) {
                e.preventDefault();
                e.stopPropagation();
                btn.click();
            }
            return;
        }

        // 2) Notes editor (title or markdown body): flush the debounced
        // autosave immediately.
        if (e.target.closest('#view-notes')) {
            e.preventDefault();
            e.stopPropagation();
            if (window.NotesView && window.NotesView.saveNow) window.NotesView.saveNow();
            return;
        }

        // 3) Space editor: same as clicking Save.
        if (e.target.closest('#view-spaces')) {
            e.preventDefault();
            e.stopPropagation();
            document.getElementById('spaceSaveBtn').click();
            return;
        }

        // 4) Inputs whose plain Enter already saves (header quick capture,
        // board inline add): their own keydown handler treats Ctrl+Enter
        // like Enter, so fall through without touching the event.
    }, true);
}

// Shared click convention for every task representation.
function wireTaskClickDelegation(containerId, selector) {
    const container = document.getElementById(containerId);
    if (!container) return;
    // Shift+mousedown extends the browser's text selection before the click
    // handler runs; on a task item Shift+click is a command (cycle status /
    // freeze), so suppress the selection gesture.
    container.addEventListener('mousedown', (e) => {
        if (e.shiftKey && e.target.closest(selector)) e.preventDefault();
    });
    container.addEventListener('click', (e) => {
        const item = e.target.closest(selector);
        if (!item) return;
        const taskId = parseInt(item.dataset.taskId);

        if (item.classList.contains('board-card')) {
            // Subtask checkbox row: check it off right from the card.
            const subtaskEl = e.target.closest('.board-card-subtask');
            if (subtaskEl) {
                e.preventDefault();
                e.stopPropagation();
                setSubtaskDone(parseInt(subtaskEl.dataset.subtaskId), true);
                return;
            }
            // + under the priority badge: inline add-subtask input (no AI).
            if (e.target.closest('.board-card-addsub')) {
                e.preventDefault();
                e.stopPropagation();
                openCardSubtaskInput(item, taskId);
                return;
            }
            // Clicks inside the inline add-subtask input must not open the modal.
            if (e.target.closest('.board-subtask-input')) {
                e.stopPropagation();
                return;
            }
            // Note badge: jump to the source note in the Notes destination.
            if (e.target.closest('.board-card-notelink')) {
                e.preventDefault();
                e.stopPropagation();
                openTaskSourceNote(taskId);
                return;
            }
        }

        // Inline priority edit (board card only): a plain click on the
        // board-card-priority badge turns it into a number input. Must not
        // trigger the card's open-edit-modal path nor the Alt multi-select path
        // — a plain click is not Alt, so stopPropagation is sufficient.
        if (item.classList.contains('board-card')
            && e.target.closest('.board-card-priority')
            && !e.altKey && !e.ctrlKey && !e.shiftKey && !e.metaKey) {
            e.preventDefault();
            e.stopPropagation();
            openPriorityEditor(item, taskId);
            return;
        }

        // Alt+click toggles a board card in/out of the multi-selection.
        if (e.altKey && item.classList.contains('board-card')) {
            e.preventDefault();
            toggleSelectTask(taskId);
            return;
        }

        // Any other modifier-less click on a board card first clears an
        // existing multi-selection, then proceeds to the normal action.
        if (selectedTaskIds.size > 0 && !e.ctrlKey && !e.shiftKey && !e.metaKey
            && item.classList.contains('board-card')) {
            clearSelection();
        }

        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            toggleTaskCompletion(taskId);
        } else if (e.shiftKey) {
            e.preventDefault();
            // Board cards: Shift+click walks the task through the workflow.
            // Everywhere else keeps the Shift+click = freeze convention.
            if (item.classList.contains('board-card')) {
                cycleTaskStatus(taskId);
            } else {
                toggleTaskFreeze(taskId);
            }
        } else {
            editTask(taskId);
        }
    });
}

// Shift+click on a board card advances the task one workflow step without
// opening the modal: To do → Doing, Doing → Blocked, Blocked → Doing,
// Done → Doing. Doing is the hub — everything not in progress is one
// Shift+click away from being worked on, and Doing ⇄ Blocked toggles.
const SHIFT_CLICK_NEXT_STATUS = { todo: 'doing', doing: 'blocked', blocked: 'doing', done: 'doing' };
const STATUS_LABELS = { todo: 'To do', doing: 'Doing', blocked: 'Blocked', done: 'Done' };

async function cycleTaskStatus(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;
    const next = SHIFT_CLICK_NEXT_STATUS[task.status] || 'doing';

    const response = await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next })
    });

    if (response.ok) {
        await loadTasks();
        calendar.refetchEvents();
        showAlert(`→ ${STATUS_LABELS[next]}`, 'info');
    } else {
        showAlert('Error updating task', 'danger');
    }
}

// ===== Kanban board =====

// --- Multi-selection helpers (board subview only) ---

function toggleSelectTask(taskId) {
    if (selectedTaskIds.has(taskId)) {
        selectedTaskIds.delete(taskId);
    } else {
        selectedTaskIds.add(taskId);
    }
    refreshSelectionVisuals();
}

function clearSelection() {
    if (selectedTaskIds.size === 0) return;
    selectedTaskIds.clear();
    refreshSelectionVisuals();
}

// Re-apply the .selected class to whichever board cards currently match the
// set. Called after every renderBoard and after every toggle.
function refreshSelectionVisuals() {
    document.querySelectorAll('#boardView .board-card').forEach(card => {
        const id = parseInt(card.dataset.taskId);
        card.classList.toggle('selected', selectedTaskIds.has(id));
    });
}

// Force every selected task to status='done' (idempotent — tasks already done
// are left untouched). Clears the selection afterwards.
async function markSelectedDone() {
    const ids = Array.from(selectedTaskIds);
    const toComplete = ids.filter(id => {
        const t = tasks.find(x => x.id === id);
        return t && !t.completed;
    });
    if (toComplete.length === 0) {
        clearSelection();
        return;
    }
    let ok = 0, fail = 0;
    for (const id of toComplete) {
        const r = await fetch(`/api/tasks/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'done' })
        });
        if (r.ok) ok++; else fail++;
    }
    clearSelection();
    await loadTasks();
    calendar.refetchEvents();
    if (fail > 0) {
        showAlert(`Marked ${ok} done, ${fail} failed`, 'danger');
    } else {
        showAlert(`✓ Marked ${ok} task${ok > 1 ? 's' : ''} done`, 'success');
    }
}

// Copy the selected tasks to the clipboard as markdown bullets:
// `- **Title**: description` (description dropped when empty).
async function copySelectedAsMarkdown() {
    const selected = tasks
        .filter(t => selectedTaskIds.has(t.id))
        .sort((a, b) => (b.priority - a.priority));
    if (selected.length === 0) return;

    const md = selected.map(t => {
        const title = (t.title || '').replace(/\n/g, ' ').trim();
        const desc = (t.description || '').trim().replace(/\n/g, ' ');
        return desc ? `- **${title}**: ${desc}` : `- **${title}**`;
    }).join('\n');

    try {
        await navigator.clipboard.writeText(md);
    } catch (err) {
        // Fallback for non-secure contexts / older browsers.
        const ta = document.createElement('textarea');
        ta.value = md;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta);
    }
    showAlert(`✓ Copied ${selected.length} task${selected.length > 1 ? 's' : ''} as markdown`, 'success');
}

// A modifier+mousedown is a click gesture (Shift=freeze, Ctrl=done,
// Alt=select), never a drag: without this filter a few px of hand jitter
// during the click starts a Sortable drag, which swallows the click and can
// drop the card into a neighbouring column (= silent status change).
function isModifierGesture(evt) {
    return !!(evt.shiftKey || evt.ctrlKey || evt.altKey || evt.metaKey);
}

function initBoardSortables() {
    document.querySelectorAll('.board-col-cards').forEach(col => {
        new Sortable(col, {
            group: 'board',
            animation: 150,
            // Intra-column drag reorders (nudges only the dragged task's
            // priority). Done stays completion-time ordered, so no sorting
            // there — cards can still be dragged in/out of it.
            sort: col.dataset.status !== 'done',
            ghostClass: 'dragging',
            filter: isModifierGesture,
            preventOnFilter: false,
            onEnd: handleBoardDrop
        });
    });
}

async function handleBoardDrop(evt) {
    const newStatus = evt.to.dataset.status;
    const oldStatus = evt.from.dataset.status;
    const draggedId = parseInt(evt.item.dataset.taskId);
    // Multi-drag: if the dragged card is part of the current selection (and
    // there's more than one selected), move every selected task to the target
    // column; otherwise it's a normal single-card move.
    const isMulti = selectedTaskIds.has(draggedId) && selectedTaskIds.size > 1;

    // Same-column drop = manual reordering: change ONLY the dragged task's
    // priority so it sorts where it was dropped. Cross-column drops below
    // keep their status-only semantics and never touch priorities.
    if (newStatus === oldStatus) {
        if (evt.newIndex === evt.oldIndex || newStatus === 'done') return;
        await reorderDraggedTask(evt.to, '.board-card', draggedId);
        return;
    }

    const ids = isMulti ? Array.from(selectedTaskIds) : [draggedId];
    let fail = 0;
    for (const id of ids) {
        const response = await fetch(`/api/tasks/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (!response.ok) fail++;
    }

    if (isMulti) clearSelection();

    if (fail > 0) {
        showAlert(`Error moving ${fail} task${fail > 1 ? 's' : ''}`, 'danger');
    }
    await loadTasks();
    calendar.refetchEvents();
}

// ===== Manual drag-reorder (board columns + calendar sidebar list) =====
//
// Lists are sorted by priority desc; dropping a card at a new spot nudges
// ONLY the dragged task's priority to a value between its new neighbours
// (fractional values allowed — the server stores floats and clamps to 0-10).
// No other task is ever touched.

function computeReorderPriority(prevEl, nextEl) {
    const priorityOf = el => {
        const t = el && tasks.find(x => x.id === parseInt(el.dataset.taskId));
        return t ? t.priority : null;
    };
    const above = priorityOf(prevEl);
    const below = priorityOf(nextEl);
    if (above === null && below === null) return null; // alone in the list
    if (above === null) return Math.min(10, below + 1); // dropped at the top
    if (below === null) return Math.max(0, above - 1);  // dropped at the bottom
    // Between two equal priorities there is nothing between to land on —
    // join the tie (secondary deadline/creation ordering takes over).
    if (above === below) return above;
    return Math.round(((above + below) / 2) * 1000) / 1000;
}

async function reorderDraggedTask(containerEl, itemSelector, draggedId) {
    const items = Array.from(containerEl.querySelectorAll(itemSelector));
    const idx = items.findIndex(el => parseInt(el.dataset.taskId) === draggedId);
    if (idx === -1) return;

    const newPriority = computeReorderPriority(items[idx - 1] || null, items[idx + 1] || null);
    const task = tasks.find(t => t.id === draggedId);
    if (newPriority === null || !task || task.priority === newPriority) return;

    const response = await fetch('/api/tasks/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: draggedId, priority: newPriority })
    });
    if (!response.ok) {
        showAlert('Error reordering task', 'danger');
    }
    await loadTasks();
}

function initBoardInlineAdd() {
    // Each kanban column always shows a quick-add input. The "+" button in the
    // column header focuses that column's input (it no longer toggles
    // visibility). Enter creates the task directly in that column (and in the
    // filtered space); Esc clears the text but leaves the form open for rapid
    // entry. While the AI parse request is in flight, the "+" icon is swapped
    // for a spinner and the input is disabled so the user sees feedback.
    // [data-status] scoping keeps other header buttons reusing the
    // .board-col-add style (e.g. the Doing auto-select magic button) out.
    document.querySelectorAll('.board-col-add[data-status]').forEach(btn => {
        btn.addEventListener('click', () => {
            const form = document.querySelector(`.board-inline-add[data-status="${btn.dataset.status}"]`);
            const input = form.querySelector('input');
            input.focus();
        });
    });

    document.querySelectorAll('.board-inline-add input').forEach(input => {
        input.addEventListener('keydown', async (e) => {
            const form = input.closest('.board-inline-add');
            const btn = document.querySelector(`.board-col-add[data-status="${form.dataset.status}"]`);
            if (e.key === 'Escape') {
                input.value = '';
                input.blur();
                return;
            }
            if (e.key !== 'Enter') return;
            const title = input.value.trim();
            if (!title) return;

            // Show loading state: swap the "+" icon for a spinner and lock the
            // input so the user gets clear feedback that creation is in flight.
            const originalBtnHTML = btn.innerHTML;
            btn.innerHTML = '<span class="board-col-add-spinner"></span>';
            btn.disabled = true;
            input.disabled = true;

            // Route through the AI parse endpoint (same as header quick-capture)
            // so the typed text gets title cleanup, deadline parsing,
            // priority/duration inference, and multi-task split. The column the
            // user typed in is honored via `force_status`; the active board space
            // filter scopes the AI prompt to that single space (hard scope) when
            // exactly one space is visible (selected, or the only one left
            // after exclusions). "All spaces" and multi-space views omit
            // `restrict_space` entirely.
            const body = { text: title, force_status: form.dataset.status };
            const visibleSpaceIds = effectiveBoardSpaceIds();
            if (visibleSpaceIds !== null && visibleSpaceIds.length === 1) {
                body.restrict_space = visibleSpaceIds[0];
            }

            try {
                const response = await fetch('/api/tasks/parse', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (response.ok) {
                    input.value = ''; // stays open for rapid entry
                    await loadTasks();
                    calendar.refetchEvents();
                } else {
                    const err = await response.json().catch(() => ({}));
                    showAlert(err.error || 'Error creating task', 'danger');
                }
            } finally {
                btn.innerHTML = originalBtnHTML;
                btn.disabled = false;
                input.disabled = false;
                input.focus();
            }
        });
    });
}

// Auto-select doing: send the user's intent to the AI, which picks the
// matching TODO tasks and moves them to the Doing column. A space-filtered
// board restricts the candidates to the selected spaces.
async function autoSelectDoing() {
    const input = document.getElementById('autoDoingInput');
    const text = input.value.trim();
    if (!text) {
        input.focus();
        return;
    }

    const btn = document.getElementById('autoDoingSubmitBtn');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span> Selecting…';
    btn.disabled = true;
    input.disabled = true;

    const body = { text };
    // Scope auto-doing to the spaces the board actually shows, so it never
    // pulls tasks from a filtered-out or excluded (greyed) space.
    const visibleSpaceIds = effectiveBoardSpaceIds();
    if (visibleSpaceIds !== null) body.space_ids = visibleSpaceIds;

    try {
        const response = await fetch('/api/tasks/auto-doing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (response.ok) {
            const result = await response.json();
            hideModalSafely(autoDoingModal, 'autoDoingModal');
            const n = result.moved.length;
            if (n > 0) {
                await loadTasks();
                calendar.refetchEvents();
                showAlert(`✨ Moved ${n} task${n > 1 ? 's' : ''} to Doing`, 'success');
            } else {
                showAlert('No matching to-do tasks found', 'info');
            }
        } else {
            const err = await response.json().catch(() => ({}));
            showAlert(err.error || 'Error selecting tasks', 'danger');
        }
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
        input.disabled = false;
    }
}

// ===== Assistant space filter (subheader chips above the chat iframe) =====
// Independent from the board filter. The selection lives in localStorage
// ('assistantSpaceFilter': JSON array of space ids, or null = all); the
// assistant iframe is same-origin and reads it via chat/public/simpler-bridge.js.

function getAssistantSpaceFilter() {
    try {
        const raw = localStorage.getItem('assistantSpaceFilter');
        const parsed = raw ? JSON.parse(raw) : null;
        return Array.isArray(parsed) && parsed.length ? parsed : null;
    } catch (e) {
        return null;
    }
}

function setAssistantSpaceFilter(filter) {
    localStorage.setItem('assistantSpaceFilter', JSON.stringify(filter));
}

function renderAssistantSpaceChips() {
    const container = document.getElementById('assistantSpaceChips');
    if (!container) return;

    const filter = getAssistantSpaceFilter();
    const chip = (label, value, active) => `
        <button class="space-chip ${active ? 'active' : ''}"
                data-space-id="${value === null ? 'all' : value}">
            ${label}
        </button>`;

    container.innerHTML =
        chip('All spaces', null, filter === null) +
        spaces.map(s => chip(escapeHtml(s.name), s.id,
            filter !== null && filter.includes(s.id))).join('');

    // Plain click = only that space; Ctrl+click = toggle it in/out of the
    // selection (empty set falls back to all); "All spaces" resets.
    container.querySelectorAll('.space-chip').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const v = btn.dataset.spaceId;
            let filter = getAssistantSpaceFilter();
            if (v === 'all') {
                filter = null;
            } else {
                const id = parseInt(v);
                if (e.ctrlKey || e.metaKey) {
                    const set = new Set(filter || []);
                    set.has(id) ? set.delete(id) : set.add(id);
                    filter = set.size ? Array.from(set) : null;
                } else {
                    filter = [id];
                }
            }
            setAssistantSpaceFilter(filter);
            renderAssistantSpaceChips();
        });
    });
}

function renderSpaceChips() {
    const container = document.getElementById('spaceChips');
    if (!container) return;

    const chip = (label, value, active, excluded) => `
        <button class="space-chip ${active ? 'active' : ''} ${excluded ? 'excluded' : ''}"
                data-space-id="${value === null ? 'all' : value}">
            ${label}
        </button>`;

    container.innerHTML =
        chip('All spaces', null, boardSpaceFilter === null && boardExcludedSpaces.size === 0, false) +
        spaces.map(s => chip(escapeHtml(s.name), s.id,
            boardSpaceFilter !== null && boardSpaceFilter.includes(s.id),
            boardExcludedSpaces.has(s.id))).join('');

    // Plain click = show only that space; Ctrl+click = toggle the space
    // in/out of the multi-space selection (empty set falls back to all);
    // Alt+click = exclude the space — the chip greys out and its tasks are
    // hidden until Alt+clicked again. "All spaces" resets both filter and
    // exclusions.
    container.querySelectorAll('.space-chip').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const v = btn.dataset.spaceId;
            if (v === 'all') {
                boardSpaceFilter = null;
                boardExcludedSpaces.clear();
            } else {
                const id = parseInt(v);
                if (e.altKey) {
                    if (boardExcludedSpaces.has(id)) {
                        boardExcludedSpaces.delete(id);
                    } else {
                        boardExcludedSpaces.add(id);
                        // An excluded space can't stay in the include set.
                        if (boardSpaceFilter !== null) {
                            boardSpaceFilter = boardSpaceFilter.filter(x => x !== id);
                            if (boardSpaceFilter.length === 0) boardSpaceFilter = null;
                        }
                    }
                } else if (e.ctrlKey || e.metaKey) {
                    const set = new Set(boardSpaceFilter || []);
                    set.has(id) ? set.delete(id) : set.add(id);
                    boardSpaceFilter = set.size ? Array.from(set) : null;
                    boardExcludedSpaces.delete(id); // explicitly picked → visible
                } else {
                    boardSpaceFilter = [id];
                    boardExcludedSpaces.delete(id); // explicitly picked → visible
                }
            }
            storeSpaceFilter();
            storeExcludedSpaces();
            renderTasksView();
        });
    });
}

function boardFilteredTasks() {
    return tasks.filter(t =>
        (boardSpaceFilter === null || boardSpaceFilter.includes(t.space_id))
        && !boardExcludedSpaces.has(t.space_id));
}

function renderBoard() {
    const filtered = boardFilteredTasks();
    const byStatus = { todo: [], doing: [], blocked: [], done: [] };
    filtered.forEach(t => {
        const status = TASK_STATUSES.includes(t.status) ? t.status : 'todo';
        byStatus[status].push(t);
    });

    // Active columns: priority desc, then deadline, then creation.
    ['todo', 'doing', 'blocked'].forEach(status => {
        byStatus[status].sort((a, b) =>
            (b.priority - a.priority) ||
            ((a.deadline ? new Date(a.deadline) : Infinity) - (b.deadline ? new Date(b.deadline) : Infinity)) ||
            (new Date(a.created_at) - new Date(b.created_at))
        );
    });
    // Done: most recently finished first, capped to keep the column scannable.
    byStatus.done.sort((a, b) =>
        new Date(b.completed_at || b.updated_at) - new Date(a.completed_at || a.updated_at));
    const doneOverflow = Math.max(0, byStatus.done.length - DONE_COLUMN_LIMIT);
    byStatus.done = byStatus.done.slice(0, DONE_COLUMN_LIMIT);

    TASK_STATUSES.forEach(status => {
        const col = document.getElementById(`col-${status}`);
        const count = document.getElementById(`count-${status}`);
        count.textContent = byStatus[status].length + (status === 'done' && doneOverflow ? `+` : '');
        col.innerHTML = byStatus[status].map(renderBoardCard).join('') ||
            `<div class="board-empty">·</div>`;
        if (status === 'done' && doneOverflow) {
            col.innerHTML += `<div class="board-done-overflow">+${doneOverflow} older done task${doneOverflow > 1 ? 's' : ''}</div>`;
        }
    });

    refreshSelectionVisuals();
}

function renderBoardCard(task) {
    const priorityClass = task.priority >= 7 ? 'priority-high' :
                         task.priority >= 4 ? 'priority-medium' : 'priority-low';
    const deadline = task.deadline ? new Date(task.deadline) : null;
    const deadlineStr = deadline ? formatDeadline(deadline) : '';
    const isSoon = deadline && (deadline - new Date()) < 24 * 60 * 60 * 1000;

    const subtasks = task.subtasks || [];
    const subtasksDone = subtasks.filter(s => s.done).length;
    // Checked subtasks never show on the card — only in the edit modal
    // (crossed out there). Doing cards list the open ones as live checkboxes.
    const openSubtasks = subtasks.filter(s => !s.done);
    const subtaskList = (task.status === 'doing' && openSubtasks.length) ? `
            <div class="board-card-subtasks">
                ${openSubtasks.map(s => `
                <label class="board-card-subtask" data-subtask-id="${s.id}">
                    <input type="checkbox"><span>${escapeHtml(s.title)}</span>
                </label>`).join('')}
            </div>` : '';

    return `
        <div class="board-card ${priorityClass} ${task.completed ? 'completed' : ''} ${task.frozen ? 'frozen' : ''}"
             data-task-id="${task.id}">
            <div class="board-card-top">
                <div class="board-card-title">${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title || '(untitled)')}</div>
                <div class="board-card-side">
                    <div class="board-card-priority ${priorityClass}">${displayPriority(task.priority)}</div>
                    <button type="button" class="board-card-addsub" title="Add subtask">+</button>
                </div>
            </div>
            <div class="board-card-meta">
                ${task.space ? `<span class="task-space">${escapeHtml(task.space)}</span>` : ''}
                ${deadlineStr ? `<span class="task-deadline ${isSoon ? 'soon' : ''}"><i class="fas fa-calendar-times"></i> ${deadlineStr}</span>` : ''}
                ${task.estimated_duration ? `<span><i class="fas fa-clock"></i> ${task.estimated_duration}min</span>` : ''}
                ${subtasks.length ? `<span class="board-card-subcount" title="Subtasks done"><i class="fas fa-list-check"></i> ${subtasksDone}/${subtasks.length}</span>` : ''}
                ${task.scheduled_start ? `<span title="Scheduled"><i class="fas fa-calendar-check"></i></span>` : ''}
                ${task.note_id ? `<button type="button" class="board-card-notelink" title="Open source note${task.note_title ? `: ${escapeHtml(task.note_title)}` : ''}"><i class="fas fa-note-sticky"></i></button>` : ''}
            </div>
            ${subtaskList}
        </div>
    `;
}

// Inline priority editor: click the board-card-priority badge (plain click) →
// the badge becomes an <input type=number>; arrows nudge, Enter commits
// (clamped 0–10, server clamps too), Esc/blur reverts. See PRD 001 §4.3.
function openPriorityEditor(cardEl, taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;

    const badge = cardEl.querySelector('.board-card-priority');
    if (!badge || badge.querySelector('input')) return; // already editing

    const original = displayPriority(task.priority);
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.max = '10';
    input.value = String(original);
    input.className = 'board-priority-input';
    input.style.width = '3em';

    badge.textContent = '';
    badge.appendChild(input);
    input.focus();
    input.select();

    let committed = false;

    function revert() {
        if (committed) return;
        badge.textContent = String(original);
    }

    async function commit() {
        if (committed) return;
        const parsed = parseInt(input.value, 10);
        if (Number.isNaN(parsed)) { committed = true; revert(); return; }
        const clamped = Math.max(0, Math.min(10, parsed));
        committed = true; // guard against blur firing during the in-flight PUT
        // Detach the input synchronously before the await.
        badge.textContent = String(clamped);
        const r = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ priority: clamped })
        });
        if (r.ok) {
            await loadTasks(); // re-render closes the editor with the saved value
        } else {
            const err = await r.json().catch(() => ({}));
            showAlert(err.error || 'Error updating priority', 'danger');
            badge.textContent = String(original);
        }
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            committed = true; // suppress the subsequent blur from reverting again
            revert();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const cur = parseInt(input.value, 10);
            if (!Number.isNaN(cur)) input.value = String(Math.min(10, cur + 1));
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            const cur = parseInt(input.value, 10);
            if (!Number.isNaN(cur)) input.value = String(Math.max(0, cur - 1));
        }
    });
    input.addEventListener('blur', () => revert());
}

// ===== Note provenance =====

// Jump from a task to the note it was promoted from (one-way link).
async function openTaskSourceNote(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task || !task.note_id) return;
    switchDestination('notes');
    const found = await NotesView.openNoteById(task.note_id);
    if (!found) showAlert('Source note not found', 'warning');
}

// ===== Subtasks =====

// The server returns the full parent task (the two-way sync may flip its
// status), so every mutation ends in a board + calendar refresh.
async function setSubtaskDone(subtaskId, done) {
    const r = await fetch(`/api/subtasks/${subtaskId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ done })
    });
    if (r.ok) {
        await loadTasks();
        calendar.refetchEvents();
    } else {
        showAlert('Error updating subtask', 'danger');
    }
    return r.ok;
}

async function addSubtaskToTask(taskId, title) {
    const r = await fetch(`/api/tasks/${taskId}/subtasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    });
    if (r.ok) {
        await loadTasks();
        calendar.refetchEvents();
    } else {
        const err = await r.json().catch(() => ({}));
        showAlert(err.error || 'Error adding subtask', 'danger');
    }
    return r.ok;
}

async function deleteSubtask(subtaskId) {
    const r = await fetch(`/api/subtasks/${subtaskId}`, { method: 'DELETE' });
    if (r.ok) {
        await loadTasks();
        calendar.refetchEvents();
    } else {
        showAlert('Error deleting subtask', 'danger');
    }
    return r.ok;
}

// + on a board card → inline input on the card; Enter adds the subtask
// directly (as-is, no AI parse), Esc/blur cancels.
function openCardSubtaskInput(cardEl, taskId) {
    const existing = cardEl.querySelector('.board-subtask-input');
    if (existing) { existing.focus(); return; }

    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'New subtask…';
    input.className = 'board-subtask-input';
    cardEl.appendChild(input);
    input.focus();

    let closed = false;
    const close = () => { if (!closed) { closed = true; input.remove(); } };

    input.addEventListener('keydown', async (e) => {
        e.stopPropagation(); // keep board shortcuts (Enter=done on selection…) out
        if (e.key === 'Enter') {
            e.preventDefault();
            const title = input.value.trim();
            if (!title) { close(); return; }
            closed = true; // loadTasks re-renders the card, removing the input
            await addSubtaskToTask(taskId, title);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    });
    input.addEventListener('blur', close);
}

// ===== Calendar (preserved as-is) =====

// Initialize FullCalendar
function initCalendar() {
    const calendarEl = document.getElementById('calendar');
    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'timeGridWeek',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'timeGridWeek,timeGridDay,dayGridMonth'
        },
        slotMinTime: '06:00:00',
        slotMaxTime: '23:00:00',
        slotDuration: '00:15:00',
        snapDuration: '00:15:00',
        height: 'auto',
        editable: true,
        droppable: true,
        eventClick: handleEventClick,
        eventDrop: handleEventDrop,
        eventResize: handleEventResize,
        events: loadCalendarEvents,
        viewDidMount: setupDayHeaderListeners,
        datesSet: setupDayHeaderListeners
    });
    calendar.render();
}

// Setup listeners for day headers to enable Ctrl+Click to freeze days
// Use event delegation on parent to avoid cloning and individual listeners
function setupDayHeaderListeners() {
    setTimeout(() => {
        // Find the header container
        const headerRow = document.querySelector('.fc-col-header');
        if (!headerRow || headerRow.dataset.listenerAttached) return;

        // Mark as having listener to prevent duplicate attachment
        headerRow.dataset.listenerAttached = 'true';

        // Use event delegation instead of individual listeners
        headerRow.addEventListener('click', function(e) {
            const header = e.target.closest('.fc-col-header-cell[data-date]');
            if (header && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                const dateStr = header.getAttribute('data-date');
                if (dateStr) {
                    freezeDay(dateStr);
                }
            }
        });

        // Add visual hints to all day headers
        const dayHeaders = document.querySelectorAll('.fc-col-header-cell[data-date]');
        dayHeaders.forEach(header => {
            header.style.cursor = 'pointer';
            header.title = 'Ctrl+Click to freeze/unfreeze all tasks on this day';
        });
    }, 50);
}

// Initialize sortable for task list
function initSortable() {
    const taskList = document.getElementById('taskList');
    sortable = new Sortable(taskList, {
        animation: 150,
        ghostClass: 'dragging',
        filter: isModifierGesture,
        preventOnFilter: false,
        onEnd: handleTaskReorder
    });
}

// Load tasks. Always fetch everything; each view filters client-side
// (the board needs the done column even when the calendar hides completed).
async function loadTasks() {
    const response = await fetch('/api/tasks?include_completed=true');
    tasks = await response.json();
    renderAll();
}

// Re-render every task representation that is currently visible.
function renderAll() {
    renderTasks();
    if (currentDestination === 'tasks' || currentDestination === null) {
        renderTasksView();
    }
}

// Toggle show completed tasks (calendar sidebar + calendar events)
function toggleShowCompleted() {
    showCompletedTasks = !showCompletedTasks;
    const btn = document.getElementById('toggleCompletedBtn');
    btn.innerHTML = showCompletedTasks
        ? '<i class="fas fa-eye-slash"></i>'
        : '<i class="fas fa-eye"></i>';
    btn.title = showCompletedTasks ? 'Hide completed tasks' : 'Show completed tasks';
    renderTasks();
    calendar.refetchEvents();
}

// Render the calendar-sidebar task list with optimized DOM updates
function renderTasks() {
    const taskList = document.getElementById('taskList');
    const visibleTasks = showCompletedTasks ? tasks : tasks.filter(t => !t.completed);

    if (visibleTasks.length === 0) {
        taskList.innerHTML = `
            <div class="text-center text-muted py-5">
                <i class="fas fa-clipboard-list fa-3x mb-3"></i>
                <p>No tasks yet. Create your first task above!</p>
            </div>
        `;
        return;
    }

    // Use DocumentFragment for efficient DOM manipulation
    const fragment = document.createDocumentFragment();

    visibleTasks.forEach(task => {
        const priorityClass = task.priority >= 7 ? 'priority-high' :
                             task.priority >= 4 ? 'priority-medium' : 'priority-low';

        const deadline = task.deadline ? new Date(task.deadline) : null;
        const deadlineStr = deadline ? formatDeadline(deadline) : '';
        const isSoon = deadline && (deadline - new Date()) < 24 * 60 * 60 * 1000;

        const taskDiv = document.createElement('div');
        taskDiv.className = `task-item ${task.completed ? 'completed' : ''} ${task.frozen ? 'frozen' : ''}`;
        taskDiv.dataset.taskId = task.id;

        taskDiv.innerHTML = `
            <div class="task-priority ${priorityClass}">${displayPriority(task.priority)}</div>
            <div class="task-title">${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title || '(untitled)')}</div>
            <div class="task-meta">
                ${task.space ? `<span class="task-space"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(task.space)}</span>` : ''}
                ${task.estimated_duration ? `<span class="task-meta-item"><i class="fas fa-clock"></i> ${task.estimated_duration}min</span>` : ''}
                ${deadlineStr ? `<span class="task-meta-item task-deadline ${isSoon ? 'soon' : ''}"><i class="fas fa-calendar-times"></i> ${deadlineStr}</span>` : ''}
                ${task.scheduled_start ? `<span class="task-meta-item"><i class="fas fa-calendar-check"></i> Scheduled</span>` : ''}
                ${task.frozen ? `<span class="task-meta-item frozen-indicator"><i class="fas fa-snowflake"></i> Frozen</span>` : ''}
            </div>
        `;

        fragment.appendChild(taskDiv);
    });

    // Clear and append in one operation
    taskList.innerHTML = '';
    taskList.appendChild(fragment);
}

// Parse task with AI (global quick capture)
async function parseTask() {
    const input = document.getElementById('quickCapture');
    const text = input.value.trim();

    if (!text) {
        showAlert('Please enter a task description', 'warning');
        input.focus();
        return;
    }

    const btn = document.getElementById('parseTaskBtn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span>';
    btn.disabled = true;

    // Prepare request body with optional space hint
    const requestBody = { text };
    if (window.selectedSpaceForNewTask) {
        requestBody.space_hint = window.selectedSpaceForNewTask;
    }

    const response = await fetch('/api/tasks/parse', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestBody)
    });

    if (response.ok) {
        input.value = '';
        await loadTasks();
        calendar.refetchEvents();
        showAlert('Task created successfully!', 'success');

        // Clear the selected space
        window.selectedSpaceForNewTask = null;
    } else {
        const error = await response.json();
        showAlert(error.error || 'Error creating task', 'danger');
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}

// Auto-schedule tasks. From the kanban board, only the currently displayed
// Doing tasks are (re)scheduled — everything else keeps its current slots.
// From any other view, all incomplete tasks are scheduled as before.
async function autoSchedule() {
    const btn = document.getElementById('scheduleBtn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span>';
    btn.disabled = true;

    let body = null;
    if (currentDestination === 'tasks' && tasksSubview === 'board') {
        body = {
            task_ids: boardFilteredTasks()
                .filter(t => t.status === 'doing' && !t.completed)
                .map(t => t.id),
        };
    }

    const response = await fetch('/api/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
    });

    if (response.ok) {
        const result = await response.json();
        await loadTasks();
        calendar.refetchEvents();
        showAlert(`Successfully scheduled ${result.scheduled_tasks} tasks!`, 'success');
    } else {
        const error = await response.json();
        showAlert(error.error || 'Error scheduling tasks', 'danger');
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}

// Load calendar events
async function loadCalendarEvents(fetchInfo, successCallback, failureCallback) {
    // Load tasks and external events in parallel for better performance
    const [taskResponse, externalResponse] = await Promise.all([
        fetch('/api/tasks?include_completed=true'),
        fetch('/api/external-events')
    ]);
    const [allTasks, externalEvents] = await Promise.all([
        taskResponse.json(),
        externalResponse.json()
    ]);
    const calendarTasks = showCompletedTasks ? allTasks : allTasks.filter(t => !t.completed);

    // Format task events
    const taskEvents = calendarTasks
        .filter(task => task.scheduled_start && task.scheduled_end)
        .map(task => {
            let className = 'task-event';
            if (task.completed) {
                className += ' completed-task';
            } else if (task.frozen) {
                className += ' frozen-task';
            }

            return {
                id: `task-${task.id}`,
                title: task.frozen ? `❄️ ${task.title}` : task.title,
                start: task.scheduled_start,
                end: task.scheduled_end,
                className: className,
                editable: !task.completed, // Prevent editing completed tasks
                extendedProps: {
                    type: 'task',
                    taskId: task.id,
                    task: task
                }
            };
        });

    // Format external events
    const formattedExternalEvents = externalEvents.map((event, index) => ({
        id: `external-${index}`,
        title: event.title,
        start: event.start,
        end: event.end,
        className: 'external-event',
        editable: false,
        extendedProps: {
            type: 'external',
            description: event.description
        }
    }));

    successCallback([...taskEvents, ...formattedExternalEvents]);
}

// Handle event click
function handleEventClick(info) {
    const event = info.event;

    if (event.extendedProps.type === 'task') {
        const isCtrl = info.jsEvent.ctrlKey || info.jsEvent.metaKey;
        const isShift = info.jsEvent.shiftKey;

        if (isCtrl) {
            // Ctrl: Mark as done/undone
            info.jsEvent.preventDefault();
            toggleTaskCompletion(event.extendedProps.taskId);
        } else if (isShift) {
            // Shift: Toggle freeze
            info.jsEvent.preventDefault();
            toggleTaskFreeze(event.extendedProps.taskId);
        } else {
            // Normal click: Edit task
            editTask(event.extendedProps.taskId);
        }
    }
}

// Handle event drop (drag)
async function handleEventDrop(info) {
    const event = info.event;

    if (event.extendedProps.type === 'task') {
        const taskId = event.extendedProps.taskId;
        const newStart = formatDateTimeLocal(event.start);
        const newEnd = formatDateTimeLocal(event.end);

        // Auto-freeze task when manually moved (unless Ctrl is pressed to skip freeze)
        const skipFreeze = info.jsEvent.ctrlKey || info.jsEvent.metaKey;
        await updateTaskSchedule(taskId, newStart, newEnd, !skipFreeze);
        await loadTasks();

        if (!skipFreeze) {
            showAlert('Task moved and frozen ❄️', 'info');
        }
    }
}

// Handle event resize
async function handleEventResize(info) {
    const event = info.event;

    if (event.extendedProps.type === 'task') {
        const taskId = event.extendedProps.taskId;
        const newStart = formatDateTimeLocal(event.start);
        const newEnd = formatDateTimeLocal(event.end);

        // Calculate new duration (rounded to 15-minute increments)
        const duration = Math.round((event.end - event.start) / 60000 / 15) * 15; // in minutes

        // Auto-freeze task when manually resized (unless Ctrl is pressed to skip freeze)
        const skipFreeze = info.jsEvent.ctrlKey || info.jsEvent.metaKey;

        await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                scheduled_start: newStart,
                scheduled_end: newEnd,
                estimated_duration: duration,
                frozen: skipFreeze ? undefined : true
            })
        });
        await loadTasks();
        calendar.refetchEvents();

        if (!skipFreeze) {
            showAlert('Task resized and frozen ❄️', 'info');
        }
    }
}

// Update task schedule
async function updateTaskSchedule(taskId, start, end, freeze = false) {
    const body = {
        scheduled_start: start,
        scheduled_end: end
    };

    if (freeze) {
        body.frozen = true;
    }

    await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    });

    calendar.refetchEvents();
}

// Handle task reorder in the calendar sidebar list: same single-task
// priority nudge as the board (only the dragged task changes).
async function handleTaskReorder(evt) {
    if (evt.newIndex === evt.oldIndex) return;
    const draggedId = parseInt(evt.item.dataset.taskId);
    await reorderDraggedTask(document.getElementById('taskList'), '.task-item', draggedId);
}

// ===== Task editing =====

// Edit task
function editTask(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;

    document.getElementById('editTaskId').value = task.id;
    document.getElementById('editTitle').value = task.title;
    document.getElementById('editDescription').value = task.description || '';
    document.getElementById('editSpace').value = task.space_id != null ? String(task.space_id) : '';
    document.getElementById('editStatus').value = task.status || 'todo';
    document.getElementById('editPriority').value = displayPriority(task.priority);
    document.getElementById('editDuration').value = task.estimated_duration || 60;

    if (task.deadline) {
        const deadline = new Date(task.deadline);
        document.getElementById('editDeadline').value = formatDateTimeLocal(deadline);
    } else {
        document.getElementById('editDeadline').value = '';
    }

    renderModalSubtasks(task.id);

    // Provenance link: only for tasks promoted from a note.
    const noteWrap = document.getElementById('editNoteLinkWrap');
    noteWrap.classList.toggle('d-none', !task.note_id);
    document.getElementById('editNoteLinkLabel').textContent =
        task.note_title ? `Open source note: ${task.note_title}` : 'Open source note';

    taskModal.show();
}

// Subtask list inside the edit modal. Unlike the task fields (batched into
// Save), subtask ops hit the API immediately — the two-way status sync can
// flip the task's status, which is re-read into the Status select.
function renderModalSubtasks(taskId) {
    const task = tasks.find(t => t.id === taskId);
    const list = document.getElementById('editSubtasksList');
    const subtasks = (task && task.subtasks) || [];
    list.innerHTML = subtasks.map(s => `
        <div class="d-flex align-items-center gap-2 mb-1" data-subtask-id="${s.id}">
            <input class="form-check-input mt-0 flex-shrink-0" type="checkbox" data-act="toggle" ${s.done ? 'checked' : ''}>
            <span class="flex-grow-1 small ${s.done ? 'subtask-done' : ''}">${escapeHtml(s.title)}</span>
            <button type="button" class="btn-close" style="font-size:.6rem" data-act="delete" aria-label="Delete subtask"></button>
        </div>`).join('') || '<div class="text-muted small">No subtasks</div>';
}

// Re-render the modal's subtask list + status select after a subtask op
// (loadTasks has already refreshed `tasks`).
function refreshModalAfterSubtaskOp() {
    const taskId = parseInt(document.getElementById('editTaskId').value);
    renderModalSubtasks(taskId);
    const task = tasks.find(t => t.id === taskId);
    if (task) document.getElementById('editStatus').value = task.status || 'todo';
}

function wireModalSubtasks() {
    const list = document.getElementById('editSubtasksList');

    list.addEventListener('click', async (e) => {
        const row = e.target.closest('[data-subtask-id]');
        if (!row) return;
        const subtaskId = parseInt(row.dataset.subtaskId);
        if (e.target.dataset.act === 'toggle') {
            await setSubtaskDone(subtaskId, e.target.checked);
            refreshModalAfterSubtaskOp();
        } else if (e.target.dataset.act === 'delete') {
            await deleteSubtask(subtaskId);
            refreshModalAfterSubtaskOp();
        }
    });

    // + Add subtask: one inline input row; Enter adds as-is (no AI), Esc cancels.
    document.getElementById('addSubtaskBtn').addEventListener('click', () => {
        const container = document.getElementById('editSubtaskNew');
        if (container.querySelector('input')) { container.querySelector('input').focus(); return; }
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.placeholder = 'New subtask…';
        container.appendChild(input);
        input.focus();
        let closed = false;
        const close = () => { if (!closed) { closed = true; input.remove(); } };
        input.addEventListener('keydown', async (e) => {
            e.stopPropagation();
            if (e.key === 'Enter') {
                e.preventDefault();
                const title = input.value.trim();
                if (!title) { close(); return; }
                const taskId = parseInt(document.getElementById('editTaskId').value);
                if (await addSubtaskToTask(taskId, title)) {
                    input.value = '';
                    refreshModalAfterSubtaskOp();
                    input.focus(); // keep adding without re-clicking +
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                close();
            }
        });
        input.addEventListener('blur', close);
    });
}

// Save task
async function saveTask() {
    const taskId = parseInt(document.getElementById('editTaskId').value);
    const data = {
        title: document.getElementById('editTitle').value,
        description: document.getElementById('editDescription').value,
        space_id: document.getElementById('editSpace').value ? parseInt(document.getElementById('editSpace').value) : null,
        status: document.getElementById('editStatus').value,
        priority: parseInt(document.getElementById('editPriority').value),
        estimated_duration: parseInt(document.getElementById('editDuration').value),
        deadline: document.getElementById('editDeadline').value ?
                 document.getElementById('editDeadline').value + ':00' : null
    };

    await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    });

    hideModalSafely(taskModal, 'taskModal');
    await loadTasks();
    calendar.refetchEvents();
    showAlert('Task updated successfully!', 'success');
}

// Delete task
async function deleteTask() {
    if (!confirm('Are you sure you want to delete this task?')) return;

    const taskId = parseInt(document.getElementById('editTaskId').value);

    await fetch(`/api/tasks/${taskId}`, {
        method: 'DELETE'
    });

    taskModal.hide();
    await loadTasks();
    calendar.refetchEvents();
    showAlert('Task deleted successfully!', 'success');
}

// Toggle task completion status
async function toggleTaskCompletion(taskId) {
    const task = tasks.find(t => t.id === taskId);
    if (!task) return;

    const response = await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            status: task.completed ? 'todo' : 'done'
        })
    });

    if (response.ok) {
        await loadTasks();
        calendar.refetchEvents();
        showAlert(
            !task.completed ? '✓ Task marked as done!' : 'Task marked as incomplete',
            !task.completed ? 'success' : 'info'
        );
    } else {
        showAlert('Error updating task', 'danger');
    }
}

// Toggle task freeze status
async function toggleTaskFreeze(taskId) {
    const response = await fetch(`/api/tasks/${taskId}/toggle-freeze`, {
        method: 'POST'
    });

    if (response.ok) {
        const result = await response.json();
        await loadTasks();
        calendar.refetchEvents();
        showAlert(
            result.frozen ? '❄️ Task frozen - will not be rescheduled' : '✓ Task unfrozen',
            result.frozen ? 'info' : 'success'
        );
    } else {
        showAlert('Error toggling freeze status', 'danger');
    }
}

// Freeze all tasks on a specific day
async function freezeDay(dateStr) {
    const response = await fetch('/api/tasks/freeze-day', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ date: dateStr })
    });

    if (response.ok) {
        const result = await response.json();
        if (result.count > 0) {
            await loadTasks();
            calendar.refetchEvents();
            showAlert(
                result.frozen
                    ? `❄️ Frozen ${result.count} task(s) on this day`
                    : `✓ Unfrozen ${result.count} task(s) on this day`,
                result.frozen ? 'info' : 'success'
            );
        } else {
            showAlert('No tasks found on this day', 'warning');
        }
    } else {
        showAlert('Error freezing day', 'danger');
    }
}

// ===== Spaces =====

// Load spaces
async function loadSpaces() {
    const response = await fetch('/api/spaces');
    spaces = await response.json();
    updateSpaceSelects();
    if (currentDestination === 'tasks') renderSpaceChips();
}

// Update space selects (value = space id; space_id is the canonical relation)
function updateSpaceSelects() {
    const select = document.getElementById('editSpace');
    select.innerHTML = '<option value="">None</option>' +
        spaces.map(space => `<option value="${space.id}">${escapeHtml(space.name)}</option>`).join('');
}

// Space management lives in the Spaces destination (spaces.js, press 5).

// ===== Calendar sources =====

// Show calendar modal
async function showCalendarModal() {
    await loadCalendarSources();
    calendarModal.show();
}

// Load calendar sources
async function loadCalendarSources() {
    const response = await fetch('/api/calendar-sources');
    const sources = await response.json();

    const list = document.getElementById('existingCalendars');
    if (sources.length > 0) {
        list.innerHTML = '<h6 class="mb-2">Existing Calendars:</h6>' +
            sources.map(source => `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span>${escapeHtml(source.name)}</span>
                    <button class="btn btn-sm btn-danger" onclick="deleteCalendarSource(${source.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `).join('');
    } else {
        list.innerHTML = '';
    }
}

// Save calendar source
async function saveCalendar() {
    const name = document.getElementById('calendarName').value;
    const url = document.getElementById('calendarUrl').value;

    if (!name || !url) {
        showAlert('Please enter both name and URL', 'warning');
        return;
    }

    await fetch('/api/calendar-sources', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name, ics_url: url })
    });

    document.getElementById('calendarName').value = '';
    document.getElementById('calendarUrl').value = '';
    await loadCalendarSources();
    calendar.refetchEvents();
    showAlert('Calendar added successfully!', 'success');
}

// Delete calendar source
async function deleteCalendarSource(sourceId) {
    if (!confirm('Are you sure you want to remove this calendar?')) return;

    await fetch(`/api/calendar-sources/${sourceId}`, {
        method: 'DELETE'
    });

    await loadCalendarSources();
    calendar.refetchEvents();
    showAlert('Calendar removed successfully!', 'success');
}

// Logout
async function logout() {
    await fetch('/logout', { method: 'POST' });
    window.location.href = '/login';
}

// ===== Utility functions =====

// Bootstrap 5 silently ignores hide() while the show transition is still
// running (its internal flag clears ~150ms AFTER the modal looks fully
// visible), so a save fired fast enough — Ctrl+Enter right as the modal
// opens — would leave the modal stuck open. Track "fully shown" through
// Bootstrap's own events (they bubble to document) and defer the hide until
// the show transition has finished.
document.addEventListener('shown.bs.modal', (e) => { e.target.dataset.fullyShown = '1'; });
document.addEventListener('hidden.bs.modal', (e) => { delete e.target.dataset.fullyShown; });

function hideModalSafely(modal, modalElementId) {
    const el = document.getElementById(modalElementId);
    if (el.dataset.fullyShown) {
        modal.hide();
    } else if (el.classList.contains('show')) {
        el.addEventListener('shown.bs.modal', () => modal.hide(), { once: true });
    }
}

function showAlert(message, type) {
    // Create alert element
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3`;
    alert.style.zIndex = '9999';
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    document.body.appendChild(alert);

    // Auto-dismiss after 3 seconds
    setTimeout(() => {
        alert.remove();
    }, 3000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Priorities are stored as floats (drag-reorder nudges create fractional
// values) but the 0-10 scale shown to the user stays integer.
function displayPriority(priority) {
    return Math.round(priority);
}

function formatDeadline(date) {
    const now = new Date();
    const diff = date - now;
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days < 0) return 'Overdue';
    if (days === 0) return 'Today';
    if (days === 1) return 'Tomorrow';
    if (days < 7) return `${days} days`;

    return date.toLocaleDateString();
}

// Format date to ISO string in local timezone (not UTC)
function formatDateTimeLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
}

// ===== Overview (grouped by space, kept as-is) =====

// Render the overview with stats and space cards
function renderOverview() {
    calculateStats();
    renderSpaceCards();
    renderOverviewDone();
}

// Toggle the recently-finished list (persisted)
function toggleOverviewDone() {
    overviewShowDone = !overviewShowDone;
    localStorage.setItem('overviewShowDone', String(overviewShowDone));
    renderOverviewDone();
}

function formatFinishedAgo(iso) {
    if (!iso) return '';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`;
    return new Date(iso).toLocaleDateString();
}

// Done tasks, most recently finished first (completed_at, updated_at fallback
// for tasks finished before the timestamp existed).
function renderOverviewDone() {
    const section = document.getElementById('overviewDoneSection');
    const btn = document.getElementById('overviewDoneToggle');
    if (!section || !btn) return;

    btn.classList.toggle('active', overviewShowDone);
    btn.innerHTML = overviewShowDone
        ? '<i class="fas fa-eye-slash"></i> Hide done'
        : '<i class="fas fa-check"></i> Show done';

    if (!overviewShowDone) {
        section.style.display = 'none';
        return;
    }
    section.style.display = 'block';

    const done = tasks
        .filter(t => t.completed)
        .sort((a, b) =>
            new Date(b.completed_at || b.updated_at) - new Date(a.completed_at || a.updated_at));

    const list = document.getElementById('overviewDoneList');
    if (done.length === 0) {
        list.innerHTML = '<div class="text-muted small py-2">Nothing finished yet.</div>';
        return;
    }
    list.innerHTML = done.map(task => `
        <div class="task-item completed" data-task-id="${task.id}">
            <div class="task-title">${escapeHtml(task.title || '(untitled)')}</div>
            <div class="task-meta">
                ${task.space ? `<span class="task-space"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(task.space)}</span>` : ''}
                <span class="task-meta-item"><i class="fas fa-check"></i> ${formatFinishedAgo(task.completed_at || task.updated_at)}</span>
            </div>
        </div>
    `).join('');
}

// Calculate and display overview statistics
function calculateStats() {
    const activeTasks = tasks.filter(t => !t.completed);
    const totalTasks = activeTasks.length;
    const scheduledTasks = activeTasks.filter(t => t.scheduled_start && t.scheduled_end).length;

    // Calculate total hours planned
    let totalMinutes = 0;
    activeTasks.forEach(task => {
        if (task.estimated_duration) {
            totalMinutes += task.estimated_duration;
        }
    });
    const hoursPlanned = (totalMinutes / 60).toFixed(1);

    // Calculate urgent tasks (deadline within 24 hours or high priority)
    const now = new Date();
    const urgentTasks = activeTasks.filter(task => {
        if (task.priority >= 8) return true;
        if (task.deadline) {
            const deadline = new Date(task.deadline);
            const hoursUntilDeadline = (deadline - now) / (1000 * 60 * 60);
            return hoursUntilDeadline > 0 && hoursUntilDeadline <= 24;
        }
        return false;
    }).length;

    // Update stat displays
    document.getElementById('statTotalTasks').textContent = totalTasks;
    document.getElementById('statHoursPlanned').textContent = hoursPlanned;
    document.getElementById('statScheduled').textContent = scheduledTasks;
    document.getElementById('statUrgent').textContent = urgentTasks;
}

// Render space cards with tasks
function renderSpaceCards() {
    const container = document.getElementById('spaceCardsContainer');
    const activeTasks = tasks.filter(t => !t.completed);

    // If no spaces, show a message
    if (spaces.length === 0) {
        container.innerHTML = `
            <div class="empty-space">
                <i class="fas fa-inbox"></i>
                <p>No spaces defined yet. Create spaces to organize your tasks!</p>
            </div>
        `;
        return;
    }

    // Group tasks by space
    const tasksBySpace = {};
    const unassignedTasks = [];

    activeTasks.forEach(task => {
        if (task.space) {
            if (!tasksBySpace[task.space]) {
                tasksBySpace[task.space] = [];
            }
            tasksBySpace[task.space].push(task);
        } else {
            unassignedTasks.push(task);
        }
    });

    // Calculate metrics for each space
    const spaceMetrics = spaces.map(space => {
        const spaceTasks = tasksBySpace[space.name] || [];
        const taskCount = spaceTasks.length;
        const totalMinutes = spaceTasks.reduce((sum, task) => sum + (task.estimated_duration || 60), 0);

        return {
            space,
            tasks: spaceTasks,
            taskCount,
            totalMinutes,
            totalHours: (totalMinutes / 60).toFixed(1)
        };
    });

    // Add unassigned space if there are unassigned tasks
    if (unassignedTasks.length > 0) {
        const totalMinutes = unassignedTasks.reduce((sum, task) => sum + (task.estimated_duration || 60), 0);
        spaceMetrics.push({
            space: { name: 'Unassigned', description: 'Tasks without a specific space' },
            tasks: unassignedTasks,
            taskCount: unassignedTasks.length,
            totalMinutes,
            totalHours: (totalMinutes / 60).toFixed(1)
        });
    }

    // Calculate total for proportional sizing
    const totalTaskCount = spaceMetrics.reduce((sum, m) => sum + m.taskCount, 0);
    const totalTime = spaceMetrics.reduce((sum, m) => sum + m.totalMinutes, 0);

    // Sort spaces: focused space first, then by task count (descending)
    spaceMetrics.sort((a, b) => {
        // Focused space always comes first
        if (a.space.name === focusedSpace) return -1;
        if (b.space.name === focusedSpace) return 1;
        // Otherwise sort by task count
        return b.taskCount - a.taskCount;
    });

    // Render space cards with proportional sizing
    const fragment = document.createDocumentFragment();

    spaceMetrics.forEach(metric => {
        if (metric.taskCount === 0) return; // Skip empty spaces

        // Calculate proportional height based on task count and time
        // Use a combination of task count (70%) and time (30%) for sizing
        const taskCountRatio = totalTaskCount > 0 ? metric.taskCount / totalTaskCount : 0;
        const timeRatio = totalTime > 0 ? metric.totalMinutes / totalTime : 0;
        const sizeRatio = (taskCountRatio * 0.7) + (timeRatio * 0.3);

        // Min height 150px, max proportional to content, scale based on ratio
        const minHeight = 150;
        const maxAdditionalHeight = 400;
        const height = minHeight + (maxAdditionalHeight * sizeRatio);

        const spaceCard = document.createElement('div');
        const isFocused = metric.space.name === focusedSpace;
        spaceCard.className = `space-card ${isFocused ? 'focused' : ''}`;
        spaceCard.style.minHeight = `${height}px`;

        spaceCard.innerHTML = `
            <div class="space-card-header">
                <div>
                    <div class="space-card-title">
                        <i class="fas fa-map-marker-alt"></i>
                        ${escapeHtml(metric.space.name)}
                        ${isFocused ? '<span class="focused-badge"><i class="fas fa-thumbtack"></i> Focused</span>' : ''}
                    </div>
                    <div class="space-card-meta">
                        <div class="space-card-meta-item">
                            <i class="fas fa-tasks"></i>
                            <span>${metric.taskCount} task${metric.taskCount !== 1 ? 's' : ''}</span>
                        </div>
                        <div class="space-card-meta-item">
                            <i class="fas fa-clock"></i>
                            <span>${metric.totalHours}h</span>
                        </div>
                    </div>
                </div>
                <div class="space-card-actions">
                    <button class="focus-btn ${isFocused ? 'active' : ''}"
                            onclick="toggleFocusSpace('${escapeHtml(metric.space.name)}')"
                            title="${isFocused ? 'Unpin this space' : 'Pin this space to top'}">
                        <i class="fas fa-thumbtack"></i>
                    </button>
                    <button class="add-task-btn" onclick="openAddTaskForSpace('${escapeHtml(metric.space.name)}')">
                        <i class="fas fa-plus"></i>
                        Add Task
                    </button>
                </div>
            </div>
            <div class="space-tasks" id="space-tasks-${escapeHtml(metric.space.name).replace(/\s+/g, '-')}">
                ${renderSpaceTasks(metric.tasks)}
            </div>
        `;

        fragment.appendChild(spaceCard);
    });

    container.innerHTML = '';
    container.appendChild(fragment);
}

// Render tasks within a space card
function renderSpaceTasks(spaceTasks) {
    if (spaceTasks.length === 0) {
        return `
            <div class="empty-space">
                <i class="fas fa-inbox"></i>
                <p>No tasks in this space</p>
            </div>
        `;
    }

    // Calculate urgency score for sorting
    const now = new Date();
    const tasksWithUrgency = spaceTasks.map(task => {
        let urgencyScore = task.priority * 10;

        if (task.deadline) {
            const deadline = new Date(task.deadline);
            const hoursUntilDeadline = (deadline - now) / (1000 * 60 * 60);

            if (hoursUntilDeadline < 0) {
                urgencyScore += 1000; // Overdue tasks are most urgent
            } else if (hoursUntilDeadline <= 24) {
                urgencyScore += 500;
            } else if (hoursUntilDeadline <= 48) {
                urgencyScore += 200;
            } else if (hoursUntilDeadline <= 168) { // 1 week
                urgencyScore += 100;
            }
        }

        return { task, urgencyScore };
    });

    // Sort by urgency (descending)
    tasksWithUrgency.sort((a, b) => b.urgencyScore - a.urgencyScore);

    // Render tasks with vertical sizing based on duration
    return tasksWithUrgency.map(({ task }) => {
        const priorityClass = task.priority >= 7 ? 'priority-high' :
                             task.priority >= 4 ? 'priority-medium' : 'priority-low';

        const deadline = task.deadline ? new Date(task.deadline) : null;
        const deadlineStr = deadline ? formatDeadline(deadline) : '';
        const isSoon = deadline && (deadline - now) < 24 * 60 * 60 * 1000;

        // Calculate height based on duration (min 60px, scale with duration)
        const duration = task.estimated_duration || 60;
        const minTaskHeight = 60;
        const heightPerHour = 30;
        const taskHeight = minTaskHeight + ((duration / 60) * heightPerHour);

        return `
            <div class="space-task-item ${priorityClass}"
                 style="min-height: ${taskHeight}px"
                 data-task-id="${task.id}">
                <div class="space-task-content">
                    <div class="space-task-title">
                        ${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title || '(untitled)')}
                    </div>
                    <div class="space-task-meta">
                        ${task.estimated_duration ?
                            `<span><i class="fas fa-clock"></i> ${task.estimated_duration}min</span>` : ''}
                        ${deadlineStr ?
                            `<span class="${isSoon ? 'task-deadline soon' : ''}"><i class="fas fa-calendar-times"></i> ${deadlineStr}</span>` : ''}
                        ${task.scheduled_start ?
                            `<span><i class="fas fa-calendar-check"></i> Scheduled</span>` : ''}
                        ${task.frozen ?
                            `<span class="frozen-indicator"><i class="fas fa-snowflake"></i> Frozen</span>` : ''}
                    </div>
                </div>
                <div class="space-task-priority ${priorityClass}">
                    ${displayPriority(task.priority)}
                </div>
            </div>
        `;
    }).join('');
}

// Open add task modal with pre-filled space
function openAddTaskForSpace(spaceName) {
    // Store the selected space for when task is created
    window.selectedSpaceForNewTask = spaceName;

    // Update modal title
    const modalTitle = document.getElementById('addTaskModalTitle');
    modalTitle.textContent = `Create Task for ${spaceName}`;

    // Clear the input
    document.getElementById('addTaskInput').value = '';

    // Show the modal (focus will be set by the shown.bs.modal event)
    addTaskModal.show();
}

// Create task from modal
async function createTaskFromModal() {
    const input = document.getElementById('addTaskInput');
    const text = input.value.trim();

    if (!text) {
        showAlert('Please enter a task description', 'warning');
        return;
    }

    const btn = document.getElementById('createTaskFromModalBtn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span> Creating...';
    btn.disabled = true;

    // Prepare request body with optional space hint
    const requestBody = { text };
    if (window.selectedSpaceForNewTask) {
        requestBody.space_hint = window.selectedSpaceForNewTask;
    }

    const response = await fetch('/api/tasks/parse', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestBody)
    });

    if (response.ok) {
        input.value = '';
        await loadTasks();
        calendar.refetchEvents();
        showAlert('Task created successfully!', 'success');

        // Clear the selected space
        window.selectedSpaceForNewTask = null;

        // Close the modal
        hideModalSafely(addTaskModal, 'addTaskModal');
    } else {
        const error = await response.json();
        showAlert(error.error || 'Error creating task', 'danger');
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}

// Toggle focus state for a space
function toggleFocusSpace(spaceName) {
    if (focusedSpace === spaceName) {
        // Unfocus
        focusedSpace = null;
        localStorage.removeItem('focusedSpace');
    } else {
        // Focus this space
        focusedSpace = spaceName;
        localStorage.setItem('focusedSpace', spaceName);
    }

    // Re-render the overview
    renderOverview();
}
