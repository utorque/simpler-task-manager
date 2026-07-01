// ===== Unified ADHD-friendly workspace shell =====
// One header, four destinations (Tasks / Calendar / Notes [/ Mail]), one
// global quick-capture input. Tasks = kanban board (home) + grouped-by-space
// overview (secondary). Calendar behavior is preserved as-is.

// Global state
let tasks = [];
let spaces = [];
let calendar;
let taskModal;
let spaceModal;
let calendarModal;
let addTaskModal;
let helpModal;
let sortable;
let showCompletedTasks = false;
let focusedSpace = localStorage.getItem('focusedSpace') || null;
let currentDestination = null;
let tasksSubview = localStorage.getItem('tasksSubview') || 'board';
let boardSpaceFilter = parseStoredSpaceFilter();

const TASK_STATUSES = ['todo', 'doing', 'blocked', 'done'];
const DONE_COLUMN_LIMIT = 30;

function parseStoredSpaceFilter() {
    const raw = localStorage.getItem('boardSpaceFilter');
    if (raw === null || raw === 'all') return null;
    const n = parseInt(raw);
    return Number.isNaN(n) ? null : n;
}

// Initialize app
document.addEventListener('DOMContentLoaded', async function() {
    // Initialize modals
    taskModal = new bootstrap.Modal(document.getElementById('taskModal'));
    spaceModal = new bootstrap.Modal(document.getElementById('spaceModal'));
    calendarModal = new bootstrap.Modal(document.getElementById('calendarModal'));
    addTaskModal = new bootstrap.Modal(document.getElementById('addTaskModal'));
    helpModal = new bootstrap.Modal(document.getElementById('helpModal'));

    // Initialize calendar
    initCalendar();

    // Initialize sortables (calendar sidebar list + kanban columns)
    initSortable();
    initBoardSortables();
    initBoardInlineAdd();

    // Load initial data
    await Promise.all([loadTasks(), loadSpaces()]);

    // Destination: deep link (#tasks/#calendar/#notes) > last used > Tasks
    const fromHash = window.location.hash.replace('#', '');
    const initial = ['tasks', 'calendar', 'notes'].includes(fromHash)
        ? fromHash
        : (localStorage.getItem('destination') || 'tasks');
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
    document.getElementById('addSpaceBtn').addEventListener('click', showSpaceModal);
    document.getElementById('addCalendarBtn').addEventListener('click', showCalendarModal);
    document.getElementById('helpBtn').addEventListener('click', () => helpModal.show());
    document.getElementById('saveTaskBtn').addEventListener('click', saveTask);
    document.getElementById('deleteTaskBtn').addEventListener('click', deleteTask);
    document.getElementById('saveCalendarBtn').addEventListener('click', saveCalendar);
    document.getElementById('createTaskFromModalBtn').addEventListener('click', createTaskFromModal);

    // Task interactions share one convention everywhere:
    // click = edit, Ctrl+click = done, Shift+click = freeze.
    wireTaskClickDelegation('taskList', '.task-item');
    wireTaskClickDelegation('spaceCardsContainer', '.space-task-item');
    wireTaskClickDelegation('boardView', '.board-card');

    // Ctrl+Enter submits the quick capture
    document.getElementById('quickCapture').addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.key === 'Enter') {
            parseTask();
        } else if (e.key === 'Escape') {
            this.blur();
        }
    });

    // Allow Ctrl+Enter in add task modal
    document.getElementById('addTaskInput').addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.key === 'Enter') {
            createTaskFromModal();
        }
    });

    // Auto-focus on add task modal when shown
    document.getElementById('addTaskModal').addEventListener('shown.bs.modal', function() {
        document.getElementById('addTaskInput').focus();
    });

    initKeyboardShortcuts();
});

// ===== Destination switching (one header, N views) =====

function switchDestination(destination) {
    if (currentDestination === destination) return;
    currentDestination = destination;

    document.querySelectorAll('.app-view').forEach(v => v.style.display = 'none');
    const view = document.getElementById(`view-${destination}`);
    if (view) view.style.display = 'block';

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
}

// Board <-> Overview toggle inside the Tasks destination (persisted)
function switchTasksSubview(subview) {
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
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (isTypingContext(e.target)) return;
        if (document.querySelector('.modal.show')) return;

        switch (e.key) {
            case '1': switchDestination('tasks'); break;
            case '2': switchDestination('calendar'); break;
            case '3': switchDestination('notes'); break;
            case '4': if (document.getElementById('view-mail')) switchDestination('mail'); break;
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

// Shared click convention for every task representation.
function wireTaskClickDelegation(containerId, selector) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.addEventListener('click', (e) => {
        const item = e.target.closest(selector);
        if (!item) return;
        const taskId = parseInt(item.dataset.taskId);
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            toggleTaskCompletion(taskId);
        } else if (e.shiftKey) {
            e.preventDefault();
            toggleTaskFreeze(taskId);
        } else {
            editTask(taskId);
        }
    });
}

// ===== Kanban board =====

function initBoardSortables() {
    document.querySelectorAll('.board-col-cards').forEach(col => {
        new Sortable(col, {
            group: 'board',
            animation: 150,
            sort: false, // intra-column order = priority/deadline (PrePRD: dedicated ordinal deferred)
            ghostClass: 'dragging',
            onEnd: handleBoardDrop
        });
    });
}

async function handleBoardDrop(evt) {
    const newStatus = evt.to.dataset.status;
    const oldStatus = evt.from.dataset.status;
    if (newStatus === oldStatus) return;

    const taskId = parseInt(evt.item.dataset.taskId);
    const response = await fetch(`/api/tasks/${taskId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
    });

    if (!response.ok) {
        showAlert('Error moving task', 'danger');
    }
    await loadTasks();
    calendar.refetchEvents();
}

function initBoardInlineAdd() {
    // "+" in a column header opens an inline input: Enter creates the task
    // directly in that column (and in the filtered space), Esc closes.
    document.querySelectorAll('.board-col-add').forEach(btn => {
        btn.addEventListener('click', () => {
            const form = document.querySelector(`.board-inline-add[data-status="${btn.dataset.status}"]`);
            form.style.display = form.style.display === 'none' ? 'block' : 'none';
            if (form.style.display === 'block') form.querySelector('input').focus();
        });
    });

    document.querySelectorAll('.board-inline-add input').forEach(input => {
        input.addEventListener('keydown', async (e) => {
            const form = input.closest('.board-inline-add');
            if (e.key === 'Escape') {
                input.value = '';
                form.style.display = 'none';
                return;
            }
            if (e.key !== 'Enter') return;
            const title = input.value.trim();
            if (!title) return;

            const response = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    status: form.dataset.status,
                    space_id: boardSpaceFilter
                })
            });
            if (response.ok) {
                input.value = ''; // stays open for rapid entry
                await loadTasks();
            } else {
                showAlert('Error creating task', 'danger');
            }
        });
    });
}

function renderSpaceChips() {
    const container = document.getElementById('spaceChips');
    if (!container) return;

    const chip = (label, value, active) => `
        <button class="space-chip ${active ? 'active' : ''}" data-space-id="${value === null ? 'all' : value}">
            ${label}
        </button>`;

    container.innerHTML =
        chip('All spaces', null, boardSpaceFilter === null) +
        spaces.map(s => chip(escapeHtml(s.name), s.id, boardSpaceFilter === s.id)).join('');

    container.querySelectorAll('.space-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            const v = btn.dataset.spaceId;
            boardSpaceFilter = v === 'all' ? null : parseInt(v);
            localStorage.setItem('boardSpaceFilter', v);
            renderTasksView();
        });
    });
}

function boardFilteredTasks() {
    if (boardSpaceFilter === null) return tasks;
    return tasks.filter(t => t.space_id === boardSpaceFilter);
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
    // Done: most recently touched first, capped to keep the column scannable.
    byStatus.done.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
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
}

function renderBoardCard(task) {
    const priorityClass = task.priority >= 7 ? 'priority-high' :
                         task.priority >= 4 ? 'priority-medium' : 'priority-low';
    const deadline = task.deadline ? new Date(task.deadline) : null;
    const deadlineStr = deadline ? formatDeadline(deadline) : '';
    const isSoon = deadline && (deadline - new Date()) < 24 * 60 * 60 * 1000;

    return `
        <div class="board-card ${priorityClass} ${task.completed ? 'completed' : ''} ${task.frozen ? 'frozen' : ''}"
             data-task-id="${task.id}">
            <div class="board-card-top">
                <div class="board-card-title">${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title)}</div>
                <div class="board-card-priority ${priorityClass}">${task.priority}</div>
            </div>
            <div class="board-card-meta">
                ${task.space ? `<span class="task-space">${escapeHtml(task.space)}</span>` : ''}
                ${deadlineStr ? `<span class="task-deadline ${isSoon ? 'soon' : ''}"><i class="fas fa-calendar-times"></i> ${deadlineStr}</span>` : ''}
                ${task.estimated_duration ? `<span><i class="fas fa-clock"></i> ${task.estimated_duration}min</span>` : ''}
                ${task.scheduled_start ? `<span title="Scheduled"><i class="fas fa-calendar-check"></i></span>` : ''}
            </div>
        </div>
    `;
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
            <div class="task-priority ${priorityClass}">${task.priority}</div>
            <div class="task-title">${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title)}</div>
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

// Auto-schedule tasks
async function autoSchedule() {
    const btn = document.getElementById('scheduleBtn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="loading"></span>';
    btn.disabled = true;

    const response = await fetch('/api/schedule', {
        method: 'POST'
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

// Handle task reorder
async function handleTaskReorder(evt) {
    const taskIds = Array.from(document.querySelectorAll('#taskList .task-item')).map(item =>
        parseInt(item.dataset.taskId)
    );

    await fetch('/api/tasks/reorder', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ task_ids: taskIds })
    });
    await loadTasks();
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
    document.getElementById('editPriority').value = task.priority;
    document.getElementById('editDuration').value = task.estimated_duration || 60;

    if (task.deadline) {
        const deadline = new Date(task.deadline);
        document.getElementById('editDeadline').value = formatDateTimeLocal(deadline);
    } else {
        document.getElementById('editDeadline').value = '';
    }

    taskModal.show();
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

    taskModal.hide();
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

// Show space modal
async function showSpaceModal() {
    await loadSpaces();
    renderSpaces();
    spaceModal.show();
}

// Render spaces
function renderSpaces() {
    const list = document.getElementById('spaceList');
    list.innerHTML = spaces.map(space => `
        <div class="card mb-3">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <h6 class="mb-0">${escapeHtml(space.name)}</h6>
                    <div>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="editSpace(${space.id})">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSpace(${space.id})">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
                ${space.description ? `<p class="text-muted small mb-2">${escapeHtml(space.description)}</p>` : ''}
                <div class="text-muted small">
                    ${space.time_constraints.length > 0 ?
                        space.time_constraints.map(c =>
                            `${getDayName(c.day)}: ${c.start} - ${c.end}`
                        ).join('<br>') :
                        'No time constraints'
                    }
                </div>
            </div>
        </div>
    `).join('');
}

// Create new space
async function createSpace() {
    const name = document.getElementById('newSpaceName').value.trim();
    const description = document.getElementById('newSpaceDescription').value.trim();

    if (!name) {
        showAlert('Please enter a space name', 'warning');
        return;
    }

    // Collect time constraints
    const constraints = [];
    const constraintInputs = document.querySelectorAll('.time-constraint-item');
    constraintInputs.forEach(item => {
        const day = parseInt(item.querySelector('.constraint-day').value);
        const start = item.querySelector('.constraint-start').value;
        const end = item.querySelector('.constraint-end').value;

        if (start && end) {
            constraints.push({ day, start, end });
        }
    });

    await fetch('/api/spaces', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            name,
            description,
            time_constraints: constraints
        })
    });

    // Reset form
    document.getElementById('newSpaceName').value = '';
    document.getElementById('newSpaceDescription').value = '';
    document.getElementById('timeConstraints').innerHTML = '';
    document.getElementById('addSpaceForm').style.display = 'none';

    await loadSpaces();
    renderSpaces();
    showAlert('Space created successfully!', 'success');
}

// Edit space
async function editSpace(spaceId) {
    const space = spaces.find(s => s.id === spaceId);
    if (!space) return;

    // Show edit form
    const list = document.getElementById('spaceList');
    list.innerHTML = `
        <div class="card mb-3">
            <div class="card-body">
                <h6 class="mb-3">Edit Space</h6>
                <div class="mb-3">
                    <label class="form-label">Name</label>
                    <input type="text" class="form-control" id="editSpaceName" value="${escapeHtml(space.name)}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Description</label>
                    <textarea class="form-control" id="editSpaceDescription" rows="2">${escapeHtml(space.description || '')}</textarea>
                </div>
                <div class="mb-3">
                    <label class="form-label">Time Constraints</label>
                    <div id="editTimeConstraints">
                        ${space.time_constraints.map((c, idx) => `
                            <div class="time-constraint-item d-flex gap-2 mb-2">
                                <select class="form-select constraint-day" style="width: auto;">
                                    ${['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((day, i) =>
                                        `<option value="${i}" ${i === c.day ? 'selected' : ''}>${day}</option>`
                                    ).join('')}
                                </select>
                                <input type="time" class="form-control constraint-start" value="${c.start}" style="width: auto;">
                                <input type="time" class="form-control constraint-end" value="${c.end}" style="width: auto;">
                                <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">
                                    <i class="fas fa-times"></i>
                                </button>
                            </div>
                        `).join('')}
                    </div>
                    <button class="btn btn-sm btn-outline-secondary mt-2" onclick="addConstraintToEdit()">
                        <i class="fas fa-plus"></i> Add Time Constraint
                    </button>
                </div>
                <div class="d-flex gap-2">
                    <button class="btn btn-primary" onclick="saveSpaceEdit(${spaceId})">Save</button>
                    <button class="btn btn-secondary" onclick="renderSpaces()">Cancel</button>
                </div>
            </div>
        </div>
    ` + spaces.filter(s => s.id !== spaceId).map(s => `
        <div class="card mb-3">
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start mb-2">
                    <h6 class="mb-0">${escapeHtml(s.name)}</h6>
                    <div>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="editSpace(${s.id})">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSpace(${s.id})">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
                ${s.description ? `<p class="text-muted small mb-2">${escapeHtml(s.description)}</p>` : ''}
                <div class="text-muted small">
                    ${s.time_constraints.length > 0 ?
                        s.time_constraints.map(c =>
                            `${getDayName(c.day)}: ${c.start} - ${c.end}`
                        ).join('<br>') :
                        'No time constraints'
                    }
                </div>
            </div>
        </div>
    `).join('');
}

// Save space edit
async function saveSpaceEdit(spaceId) {
    const name = document.getElementById('editSpaceName').value.trim();
    const description = document.getElementById('editSpaceDescription').value.trim();

    if (!name) {
        showAlert('Please enter a space name', 'warning');
        return;
    }

    // Collect time constraints
    const constraints = [];
    const constraintInputs = document.querySelectorAll('#editTimeConstraints .time-constraint-item');
    constraintInputs.forEach(item => {
        const day = parseInt(item.querySelector('.constraint-day').value);
        const start = item.querySelector('.constraint-start').value;
        const end = item.querySelector('.constraint-end').value;

        if (start && end) {
            constraints.push({ day, start, end });
        }
    });

    await fetch(`/api/spaces/${spaceId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            name,
            description,
            time_constraints: constraints
        })
    });

    await loadSpaces();
    renderSpaces();
    showAlert('Space updated successfully!', 'success');
}

// Delete space
async function deleteSpace(spaceId) {
    if (!confirm('Are you sure you want to delete this space?')) return;

    await fetch(`/api/spaces/${spaceId}`, {
        method: 'DELETE'
    });

    await loadSpaces();
    renderSpaces();
    showAlert('Space deleted successfully!', 'success');
}

// Show add space form
function showAddSpaceForm() {
    document.getElementById('addSpaceForm').style.display = 'block';
}

// Add time constraint
function addTimeConstraint() {
    const container = document.getElementById('timeConstraints');
    const div = document.createElement('div');
    div.className = 'time-constraint-item d-flex gap-2 mb-2';
    div.innerHTML = `
        <select class="form-select constraint-day" style="width: auto;">
            <option value="0">Monday</option>
            <option value="1">Tuesday</option>
            <option value="2">Wednesday</option>
            <option value="3">Thursday</option>
            <option value="4">Friday</option>
            <option value="5">Saturday</option>
            <option value="6">Sunday</option>
        </select>
        <input type="time" class="form-control constraint-start" style="width: auto;">
        <input type="time" class="form-control constraint-end" style="width: auto;">
        <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;
    container.appendChild(div);
}

// Add constraint to edit form
function addConstraintToEdit() {
    const container = document.getElementById('editTimeConstraints');
    const div = document.createElement('div');
    div.className = 'time-constraint-item d-flex gap-2 mb-2';
    div.innerHTML = `
        <select class="form-select constraint-day" style="width: auto;">
            <option value="0">Monday</option>
            <option value="1">Tuesday</option>
            <option value="2">Wednesday</option>
            <option value="3">Thursday</option>
            <option value="4">Friday</option>
            <option value="5">Saturday</option>
            <option value="6">Sunday</option>
        </select>
        <input type="time" class="form-control constraint-start" style="width: auto;">
        <input type="time" class="form-control constraint-end" style="width: auto;">
        <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;
    container.appendChild(div);
}

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

function getDayName(dayIndex) {
    const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    return days[dayIndex];
}

// ===== Overview (grouped by space, kept as-is) =====

// Render the overview with stats and space cards
function renderOverview() {
    calculateStats();
    renderSpaceCards();
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
                        ${task.frozen ? '❄️ ' : ''}${escapeHtml(task.title)}
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
                    ${task.priority}
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
        addTaskModal.hide();
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
