/**
 * MiniBoard - Vanilla ES6+ Kanban Frontend
 * Communicates directly with /api/tasks REST endpoints.
 */

(() => {
  'use strict';

  // API Endpoints
  const API_BASE = '/api/tasks';
  const API_HEALTH = '/health';

  // Application State
  const state = {
    tasks: [],
    editingTaskId: null,
    isSubmitting: false,
    notificationTimeout: null
  };

  // DOM Elements
  const elements = {
    taskForm: document.getElementById('task-form'),
    taskTitleInput: document.getElementById('task-title-input'),
    taskSubmitBtn: document.getElementById('task-submit-btn'),
    notificationBanner: document.getElementById('notification-banner'),
    notificationIcon: document.getElementById('notification-icon'),
    notificationMessage: document.getElementById('notification-message'),
    notificationCloseBtn: document.getElementById('notification-close-btn'),
    connectionStatus: document.getElementById('connection-status'),
    connectionStatusText: document.getElementById('connection-status-text'),
    totalCount: document.getElementById('total-tasks-count'),
    todoCount: document.getElementById('todo-tasks-count'),
    doingCount: document.getElementById('doing-tasks-count'),
    doneCount: document.getElementById('done-tasks-count'),
    badgeTodo: document.getElementById('badge-todo'),
    badgeDoing: document.getElementById('badge-doing'),
    badgeDone: document.getElementById('badge-done'),
    listTodo: document.getElementById('list-todo'),
    listDoing: document.getElementById('list-doing'),
    listDone: document.getElementById('list-done'),
    emptyTodo: document.getElementById('empty-todo'),
    emptyDoing: document.getElementById('empty-doing'),
    emptyDone: document.getElementById('empty-done'),
    dropzones: document.querySelectorAll('.task-dropzone')
  };

  // ==========================================================================
  // Notification Management
  // ==========================================================================

  /**
   * Display a status/notification banner.
   * @param {string} message - Message text to display.
   * @param {'success' | 'error' | 'warning' | 'info'} type - Notification style.
   * @param {number} duration - Auto-dismiss timeout in ms (default 4000).
   */
  function showNotification(message, type = 'info', duration = 4000) {
    if (state.notificationTimeout) {
      clearTimeout(state.notificationTimeout);
      state.notificationTimeout = null;
    }

    const icons = {
      success: '✓',
      error: '⚠',
      warning: '!',
      info: 'ℹ'
    };

    const banner = elements.notificationBanner;
    banner.className = `notification-banner ${type}`;
    elements.notificationIcon.textContent = icons[type] || 'ℹ';
    elements.notificationMessage.textContent = message;

    if (duration > 0) {
      state.notificationTimeout = setTimeout(() => {
        hideNotification();
      }, duration);
    }
  }

  function hideNotification() {
    if (state.notificationTimeout) {
      clearTimeout(state.notificationTimeout);
      state.notificationTimeout = null;
    }
    elements.notificationBanner.className = 'notification-banner hidden';
    elements.notificationMessage.textContent = '';
  }

  function updateConnectionStatus(isOnline) {
    if (isOnline) {
      elements.connectionStatus.classList.remove('offline');
      elements.connectionStatusText.textContent = 'Online';
    } else {
      elements.connectionStatus.classList.add('offline');
      elements.connectionStatusText.textContent = 'Offline';
    }
  }

  // ==========================================================================
  // Timestamp Formatting
  // ==========================================================================

  /**
   * Format ISO 8601 UTC timestamp to readable display.
   * @param {string} isoString
   * @returns {string}
   */
  function formatTimestamp(isoString) {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      if (isNaN(date.getTime())) return isoString;
      
      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();

      const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      if (isToday) {
        return `Today at ${timeStr}`;
      }
      return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${timeStr}`;
    } catch {
      return isoString;
    }
  }

  // ==========================================================================
  // API Requests
  // ==========================================================================

  /**
   * Check backend health status.
   */
  async function checkHealth() {
    try {
      const res = await fetch(API_HEALTH);
      if (res.ok) {
        updateConnectionStatus(true);
      } else {
        updateConnectionStatus(false);
      }
    } catch {
      updateConnectionStatus(false);
    }
  }

  /**
   * Fetch all tasks from GET /api/tasks.
   */
  async function fetchTasks() {
    try {
      const res = await fetch(API_BASE);
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${res.status}: Failed to fetch tasks`);
      }
      const data = await res.json();
      state.tasks = Array.isArray(data) ? data : [];
      updateConnectionStatus(true);
      render();
    } catch (err) {
      updateConnectionStatus(false);
      showNotification(`Error loading tasks: ${err.message}`, 'error', 5000);
    }
  }

  /**
   * Create a new task via POST /api/tasks.
   * @param {string} title
   */
  async function createTask(title) {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      showNotification('Task title cannot be empty', 'warning');
      elements.taskTitleInput.focus();
      return;
    }

    state.isSubmitting = true;
    elements.taskSubmitBtn.disabled = true;

    try {
      const res = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmedTitle, status: 'TODO' })
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `Failed to create task (Status ${res.status})`);
      }

      state.tasks.push(data);
      elements.taskTitleInput.value = '';
      updateConnectionStatus(true);
      showNotification('Task created successfully', 'success');
      render();
    } catch (err) {
      showNotification(err.message, 'error');
    } finally {
      state.isSubmitting = false;
      elements.taskSubmitBtn.disabled = false;
      elements.taskTitleInput.focus();
    }
  }

  /**
   * Update task status via PATCH /api/tasks/<id>.
   * @param {number} id
   * @param {'TODO' | 'DOING' | 'DONE'} newStatus
   */
  async function updateTaskStatus(id, newStatus) {
    const taskIndex = state.tasks.findIndex(t => t.id === Number(id));
    if (taskIndex === -1) return;

    const task = state.tasks[taskIndex];
    if (task.status === newStatus) return;

    const previousStatus = task.status;
    // Optimistic update
    task.status = newStatus;
    render();

    try {
      const res = await fetch(`${API_BASE}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `Failed to update status (Status ${res.status})`);
      }

      // Sync with server updated data
      state.tasks[taskIndex] = data;
      updateConnectionStatus(true);
      showNotification(`Task moved to ${newStatus}`, 'success');
      render();
    } catch (err) {
      // Revert optimistic update
      task.status = previousStatus;
      render();
      showNotification(`Status update failed: ${err.message}`, 'error');
    }
  }

  /**
   * Update task title via PATCH /api/tasks/<id>.
   * @param {number} id
   * @param {string} newTitle
   */
  async function updateTaskTitle(id, newTitle) {
    const trimmedTitle = newTitle.trim();
    if (!trimmedTitle) {
      showNotification('Task title cannot be empty', 'warning');
      return;
    }

    const taskIndex = state.tasks.findIndex(t => t.id === Number(id));
    if (taskIndex === -1) return;

    const task = state.tasks[taskIndex];
    const previousTitle = task.title;

    // Optimistic update
    task.title = trimmedTitle;
    state.editingTaskId = null;
    render();

    try {
      const res = await fetch(`${API_BASE}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmedTitle })
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `Failed to update title (Status ${res.status})`);
      }

      state.tasks[taskIndex] = data;
      updateConnectionStatus(true);
      showNotification('Task title updated', 'success');
      render();
    } catch (err) {
      task.title = previousTitle;
      render();
      showNotification(`Title update failed: ${err.message}`, 'error');
    }
  }

  /**
   * Delete a task via DELETE /api/tasks/<id>.
   * @param {number} id
   */
  async function deleteTask(id) {
    const taskIndex = state.tasks.findIndex(t => t.id === Number(id));
    if (taskIndex === -1) return;

    const task = state.tasks[taskIndex];
    const confirmDelete = window.confirm(`Are you sure you want to delete task "${task.title}"?`);
    if (!confirmDelete) return;

    // Remove optimistically
    const [removedTask] = state.tasks.splice(taskIndex, 1);
    render();

    try {
      const res = await fetch(`${API_BASE}/${id}`, {
        method: 'DELETE'
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `Failed to delete task (Status ${res.status})`);
      }

      updateConnectionStatus(true);
      showNotification('Task deleted', 'success');
    } catch (err) {
      // Revert deletion
      state.tasks.splice(taskIndex, 0, removedTask);
      render();
      showNotification(`Delete failed: ${err.message}`, 'error');
    }
  }

  // ==========================================================================
  // DOM Rendering
  // ==========================================================================

  /**
   * Create DOM node for a single task card.
   * @param {object} task
   * @returns {HTMLElement}
   */
  function createTaskCard(task) {
    const card = document.createElement('article');
    card.className = 'task-card';
    card.id = `task-card-${task.id}`;
    card.setAttribute('data-id', String(task.id));
    card.setAttribute('data-status', task.status);

    const isEditing = state.editingTaskId === task.id;
    card.setAttribute('draggable', isEditing ? 'false' : 'true');

    // Drag-and-drop event listeners on card
    card.addEventListener('dragstart', (e) => {
      if (state.editingTaskId !== null) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.setData('text/plain', String(task.id));
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
    });

    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      elements.dropzones.forEach(dz => dz.classList.remove('drag-over'));
    });

    if (isEditing) {
      // Inline Editing Form
      const editBox = document.createElement('div');
      editBox.className = 'inline-edit-box';

      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'inline-edit-input';
      input.value = task.title;
      input.maxLength = 500;
      input.setAttribute('aria-label', 'Edit task title');

      const actions = document.createElement('div');
      actions.className = 'inline-edit-actions';

      const saveBtn = document.createElement('button');
      saveBtn.type = 'button';
      saveBtn.className = 'btn btn-sm btn-primary';
      saveBtn.textContent = 'Save';
      saveBtn.addEventListener('click', () => updateTaskTitle(task.id, input.value));

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn btn-sm btn-secondary';
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', () => {
        state.editingTaskId = null;
        render();
      });

      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          updateTaskTitle(task.id, input.value);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          state.editingTaskId = null;
          render();
        }
      });

      actions.appendChild(cancelBtn);
      actions.appendChild(saveBtn);
      editBox.appendChild(input);
      editBox.appendChild(actions);
      card.appendChild(editBox);

      // Focus input after element is attached to DOM
      setTimeout(() => {
        input.focus();
        input.select();
      }, 0);

      return card;
    }

    // Normal Card Header (Title & Edit Icon)
    const header = document.createElement('div');
    header.className = 'card-header';

    const titleEl = document.createElement('h3');
    titleEl.className = 'task-title';
    titleEl.textContent = task.title;
    titleEl.title = 'Double-click to edit title';
    titleEl.addEventListener('dblclick', () => {
      state.editingTaskId = task.id;
      render();
    });

    header.appendChild(titleEl);
    card.appendChild(header);

    // Metadata (Timestamps)
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    
    const timeDisplay = formatTimestamp(task.updated_at || task.created_at);
    const timeLabel = task.updated_at && task.updated_at !== task.created_at ? 'Updated' : 'Created';
    meta.innerHTML = `<span class="meta-item" title="${timeLabel}: ${task.updated_at || task.created_at}">⏱ ${timeDisplay}</span>`;
    card.appendChild(meta);

    // Action Controls (Status Transitions & Edit / Delete)
    const cardActions = document.createElement('div');
    cardActions.className = 'card-actions';

    const transitions = document.createElement('div');
    transitions.className = 'action-transitions';

    // Status Buttons depending on current column
    if (task.status === 'TODO') {
      const btnDoing = createTransitionButton('DOING →', 'to-doing', () => updateTaskStatus(task.id, 'DOING'));
      const btnDone = createTransitionButton('DONE ✓', 'to-done', () => updateTaskStatus(task.id, 'DONE'));
      transitions.appendChild(btnDoing);
      transitions.appendChild(btnDone);
    } else if (task.status === 'DOING') {
      const btnTodo = createTransitionButton('← TODO', 'to-todo', () => updateTaskStatus(task.id, 'TODO'));
      const btnDone = createTransitionButton('DONE ✓', 'to-done', () => updateTaskStatus(task.id, 'DONE'));
      transitions.appendChild(btnTodo);
      transitions.appendChild(btnDone);
    } else if (task.status === 'DONE') {
      const btnDoing = createTransitionButton('← DOING', 'to-doing', () => updateTaskStatus(task.id, 'DOING'));
      const btnTodo = createTransitionButton('← TODO', 'to-todo', () => updateTaskStatus(task.id, 'TODO'));
      transitions.appendChild(btnDoing);
      transitions.appendChild(btnTodo);
    }

    cardActions.appendChild(transitions);

    // Edit and Delete buttons
    const manageActions = document.createElement('div');
    manageActions.className = 'action-manage';

    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'btn-icon btn-edit';
    editBtn.title = 'Edit task title';
    editBtn.setAttribute('aria-label', `Edit task: ${task.title}`);
    editBtn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
      </svg>
    `;
    editBtn.addEventListener('click', () => {
      state.editingTaskId = task.id;
      render();
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn-icon btn-delete';
    deleteBtn.title = 'Delete task';
    deleteBtn.setAttribute('aria-label', `Delete task: ${task.title}`);
    deleteBtn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        <line x1="10" y1="11" x2="10" y2="17"></line>
        <line x1="14" y1="11" x2="14" y2="17"></line>
      </svg>
    `;
    deleteBtn.addEventListener('click', () => deleteTask(task.id));

    manageActions.appendChild(editBtn);
    manageActions.appendChild(deleteBtn);
    cardActions.appendChild(manageActions);

    card.appendChild(cardActions);
    return card;
  }

  function createTransitionButton(label, extraClass, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `btn-transition ${extraClass}`;
    btn.textContent = label;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      onClick();
    });
    return btn;
  }

  /**
   * Re-render all columns, cards, empty states, and badges.
   */
  function render() {
    const todoTasks = state.tasks.filter(t => t.status === 'TODO');
    const doingTasks = state.tasks.filter(t => t.status === 'DOING');
    const doneTasks = state.tasks.filter(t => t.status === 'DONE');

    // Update Counts
    elements.totalCount.textContent = state.tasks.length;
    elements.todoCount.textContent = todoTasks.length;
    elements.doingCount.textContent = doingTasks.length;
    elements.doneCount.textContent = doneTasks.length;

    elements.badgeTodo.textContent = todoTasks.length;
    elements.badgeDoing.textContent = doingTasks.length;
    elements.badgeDone.textContent = doneTasks.length;

    // Render TODO list
    elements.listTodo.innerHTML = '';
    todoTasks.forEach(task => elements.listTodo.appendChild(createTaskCard(task)));
    elements.emptyTodo.classList.toggle('hidden', todoTasks.length > 0);

    // Render DOING list
    elements.listDoing.innerHTML = '';
    doingTasks.forEach(task => elements.listDoing.appendChild(createTaskCard(task)));
    elements.emptyDoing.classList.toggle('hidden', doingTasks.length > 0);

    // Render DONE list
    elements.listDone.innerHTML = '';
    doneTasks.forEach(task => elements.listDone.appendChild(createTaskCard(task)));
    elements.emptyDone.classList.toggle('hidden', doneTasks.length > 0);
  }

  // ==========================================================================
  // Drag and Drop Initialization
  // ==========================================================================

  function setupDragAndDrop() {
    elements.dropzones.forEach(dropzone => {
      const targetStatus = dropzone.dataset.status;

      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        dropzone.classList.add('drag-over');
      });

      dropzone.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dropzone.classList.add('drag-over');
      });

      dropzone.addEventListener('dragleave', (e) => {
        // Only remove class if cursor leaves the dropzone element
        if (!dropzone.contains(e.relatedTarget)) {
          dropzone.classList.remove('drag-over');
        }
      });

      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('drag-over');

        const taskId = e.dataTransfer.getData('text/plain');
        if (taskId && targetStatus) {
          updateTaskStatus(Number(taskId), targetStatus);
        }
      });
    });
  }

  // ==========================================================================
  // Event Listeners & Bootstrap
  // ==========================================================================

  function setupEventListeners() {
    // Task creation submission
    elements.taskForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!state.isSubmitting) {
        createTask(elements.taskTitleInput.value);
      }
    });

    // Close notification button
    elements.notificationCloseBtn.addEventListener('click', hideNotification);

    // Periodic connectivity check
    setInterval(checkHealth, 30000);
  }

  // Initialization
  function init() {
    setupDragAndDrop();
    setupEventListeners();
    checkHealth();
    fetchTasks();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
