/* Factory Control UI — Alpine CSP store and JSON API adapter. */
(() => {
  'use strict';

  const API = '/api/v1';
  const ACTIVE_RUN_STATES = new Set(['PENDING', 'RUNNING', 'ACTIVE', 'EXECUTING']);

  function numberOrDash(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return new Intl.NumberFormat().format(Number(value));
  }

  function bytesOrDash(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const bytes = Number(value);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function durationOrDash(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    const seconds = Number(value) / 1000;
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds % 60);
    return `${minutes}m ${rest}s`;
  }

  function relativeTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    if (abs < 60) return formatter.format(seconds, 'second');
    if (abs < 3600) return formatter.format(Math.round(seconds / 60), 'minute');
    if (abs < 86400) return formatter.format(Math.round(seconds / 3600), 'hour');
    return formatter.format(Math.round(seconds / 86400), 'day');
  }

  function statusVariant(status) {
    const normalized = String(status || '').toUpperCase();
    if (['DONE', 'COMPLETE', 'COMPLETED', 'SUCCESS', 'REAL_PROVIDER_CERTIFIED', 'AVAILABLE'].includes(normalized)) return 'success';
    if (['FAILED', 'TIMED_OUT', 'CONFLICTED', 'CANCELLED', 'PROFILE_INVALID'].includes(normalized)) return 'danger';
    if (['BLOCKED', 'AUTH_BLOCKED', 'PROFILE_UNAVAILABLE', 'FREEBUFF_HEADLESS_BLOCKED', 'BLOCKED_EXTERNAL_COMPATIBILITY'].includes(normalized)) return 'warning';
    if (['RUNNING', 'EXECUTING', 'READY', 'REVIEW', 'TRANSPORT_CERTIFIED'].includes(normalized)) return 'brand';
    return 'neutral';
  }

  async function readJson(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`Invalid JSON response (${response.status})`);
    }
  }

  document.addEventListener('alpine:init', () => {
    Alpine.data('factoryControl', () => ({
      view: 'overview',
      snapshot: { factory: {}, board: { columns: [], counts: {}, task_count: 0 }, providers: [], goals: [], runs: [], metrics: {} },
      system: { profiles: {}, context_policy: { roles: {} }, reasoning_policy: { escalation_policy: {} }, toolchain: {} },
      systemLoaded: false,
      taskDetail: { task: {}, attempts: [], events: [], telemetry: [] },
      goalDetail: { state: {}, summary: {}, goal_spec: { acceptance_criteria: [] }, plan: null },
      runDetail: { run: {}, tasks: [] },
      selectedDetailType: '',
      selectedGoalId: null,
      selectedRunId: null,
      detailOpen: false,
      loading: true,
      detailLoading: false,
      error: '',
      notice: '',
      etag: '',
      timer: null,
      requestController: null,
      lastUpdatedAt: null,

      init() {
        document.addEventListener('visibilitychange', () => this.reschedule(0));
        this.refresh();
      },

      destroy() {
        if (this.timer) window.clearTimeout(this.timer);
        if (this.requestController) this.requestController.abort();
      },

      get projectName() {
        return this.snapshot?.factory?.project_name || 'Factory project';
      },

      get factoryVersion() {
        return this.snapshot?.factory?.version || '—';
      },

      get isActive() {
        if (this.snapshot?.factory?.active) return true;
        return (this.snapshot?.runs || []).some(run => ACTIVE_RUN_STATES.has(String(run.run_state || '').toUpperCase()));
      },

      get activeGoal() {
        return this.snapshot.active_goal || {};
      },

      get hasActiveGoal() {
        return Boolean(this.snapshot.active_goal && this.snapshot.active_goal.goal_id);
      },

      get selectedRunLabel() {
        return this.snapshot.selected_run_id ? `Run ${this.snapshot.selected_run_id}` : 'No run selected';
      },

      get boardColumns() {
        return this.snapshot?.board?.columns || [];
      },

      get providers() {
        return this.snapshot?.providers || [];
      },

      get goals() {
        return this.snapshot?.goals || [];
      },

      get runs() {
        return this.snapshot?.runs || [];
      },

      get metrics() {
        return this.snapshot?.metrics || {};
      },

      get overviewMetrics() {
        return [
          { label: 'Tasks', value: numberOrDash(this.snapshot?.board?.task_count), hint: 'selected run' },
          { label: 'Running', value: numberOrDash(this.snapshot?.board?.counts?.RUNNING || 0), hint: 'active tasks' },
          { label: 'Blocked', value: numberOrDash(this.snapshot?.board?.counts?.BLOCKED || 0), hint: 'needs attention' },
          { label: 'Reasoning', value: numberOrDash(this.metrics.reasoning_tokens), hint: 'provider-reported tokens' },
          { label: 'Input', value: numberOrDash(this.metrics.input_tokens), hint: 'provider-reported tokens' },
          { label: 'Duration', value: durationOrDash(this.metrics.duration_ms), hint: 'observed selected run' },
        ];
      },

      get goalCriteria() {
        return this.goalDetail.goal_spec?.acceptance_criteria || [];
      },

      get selectedRunTasks() {
        return this.runDetail.tasks || [];
      },

      get boardProgress() {
        const counts = this.snapshot?.board?.counts || {};
        const total = Number(this.snapshot?.board?.task_count || 0);
        if (!total) return 0;
        return Math.round((Number(counts.DONE || 0) / total) * 100);
      },

      get systemProfiles() {
        const profiles = this.system.profiles || {};
        return Object.keys(profiles).sort().map(profileId => ({
          profile_id: profileId,
          ...profiles[profileId],
          certification_status: profiles[profileId]?.certification?.status || 'UNKNOWN',
        }));
      },

      get systemContextRoles() {
        const roles = this.system?.context_policy?.roles || {};
        return Object.keys(roles).sort().map(role => ({ role, ...roles[role] }));
      },

      get selectedTask() {
        return this.taskDetail.task || {};
      },

      get selectedTaskAttempts() { return this.taskDetail.attempts || []; },
      get selectedTaskEvents() { return this.taskDetail.events || []; },
      get selectedTaskTelemetry() { return this.taskDetail.telemetry || []; },
      get hasChangedPaths() { return (this.selectedTask.changed_paths || []).length > 0; },
      get reasoningPolicyVersion() { return this.system.reasoning_policy?.policy_version || '—'; },
      get reasoningPolicyStatus() { return this.system.reasoning_policy?.status || '—'; },
      get reasoningEscalationLimit() { return this.system.reasoning_policy?.escalation_policy?.max_effort_escalations_per_task || '—'; },

      pollDelay() {
        if (document.hidden) return 30000;
        return this.isActive ? 2000 : 8000;
      },

      reschedule(delay) {
        if (this.timer) window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => this.refresh(), delay === undefined ? this.pollDelay() : delay);
      },

      async request(path, options = {}) {
        const response = await fetch(path, {
          cache: 'no-store',
          credentials: 'same-origin',
          ...options,
        });
        if (!response.ok) {
          const payload = await readJson(response).catch(() => ({}));
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        return readJson(response);
      },

      async refresh() {
        if (this.requestController) this.requestController.abort();
        this.requestController = new AbortController();
        const headers = {};
        if (this.etag) headers['If-None-Match'] = this.etag;
        try {
          const response = await fetch(`${API}/snapshot`, {
            cache: 'no-store',
            credentials: 'same-origin',
            headers,
            signal: this.requestController.signal,
          });
          if (response.status === 304) {
            this.error = '';
            this.loading = false;
            this.lastUpdatedAt = new Date().toISOString();
            return;
          }
          if (!response.ok) {
            const payload = await readJson(response).catch(() => ({}));
            throw new Error(payload.error || `HTTP ${response.status}`);
          }
          this.snapshot = await readJson(response);
          this.etag = response.headers.get('ETag') || '';
          this.error = '';
          this.loading = false;
          this.lastUpdatedAt = new Date().toISOString();
        } catch (error) {
          if (error?.name !== 'AbortError') {
            this.error = error?.message || String(error);
            this.loading = false;
          }
        } finally {
          this.requestController = null;
          this.reschedule();
        }
      },

      setView(name) {
        this.view = name;
        if (name === 'system' && !this.systemLoaded) this.loadSystem();
      },

      async loadSystem() {
        try {
          this.system = await this.request(`${API}/system`);
          this.systemLoaded = true;
        } catch (error) {
          this.error = error?.message || String(error);
        }
      },

      async openTask(task) {
        if (!task?.run_id || !task?.task_id) return;
        this.detailLoading = true;
        this.detailOpen = true;
        this.taskDetail = { task: {}, attempts: [], events: [], telemetry: [] };
        try {
          this.taskDetail = await this.request(`${API}/runs/${encodeURIComponent(task.run_id)}/tasks/${encodeURIComponent(task.task_id)}`);
        } catch (error) {
          this.error = error?.message || String(error);
          this.detailOpen = false;
        } finally {
          this.detailLoading = false;
        }
      },

      closeTask() {
        this.detailOpen = false;
      },

      async selectGoal(goal) {
        if (!goal?.goal_id) return;
        this.selectedGoalId = goal.goal_id;
        this.selectedDetailType = 'goal';
        this.goalDetail = { state: {}, summary: {}, goal_spec: { acceptance_criteria: [] }, plan: null };
        try {
          this.goalDetail = await this.request(`${API}/goals/${encodeURIComponent(goal.goal_id)}`);
        } catch (error) {
          this.error = error?.message || String(error);
        }
      },

      async selectRun(run) {
        if (!run?.run_id) return;
        this.selectedRunId = run.run_id;
        this.selectedDetailType = 'run';
        this.runDetail = { run: {}, tasks: [] };
        try {
          this.runDetail = await this.request(`${API}/runs/${encodeURIComponent(run.run_id)}`);
        } catch (error) {
          this.error = error?.message || String(error);
        }
      },

      async resumeGoal(goal) {
        if (!goal?.goal_id || !goal?.resumable) return;
        if (!window.confirm(`Resume ${goal.goal_id}? This delegates to Factory's existing goal resume command and may consume provider usage.`)) return;
        try {
          const result = await this.request(`${API}/goals/${encodeURIComponent(goal.goal_id)}/resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          });
          this.notice = `Resume accepted (PID ${result.pid}).`;
          this.reschedule(500);
        } catch (error) {
          this.error = error?.message || String(error);
        }
      },

      clearNotice() {
        this.notice = '';
      },

      yesNoUnknown(value) {
        if (value === true) return 'yes';
        if (value === false) return 'no';
        return 'unknown';
      },

      attemptDescriptor(attempt) {
        return [attempt?.profile_id || attempt?.worker_id, attempt?.model, attempt?.effort].filter(Boolean).join(' · ');
      },

      statusVariant,
      numberOrDash,
      bytesOrDash,
      durationOrDash,
      relativeTime,
    }));
  });
})();
