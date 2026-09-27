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
    if (['DONE', 'COMPLETE', 'COMPLETED', 'SUCCESS', 'PASS', 'REAL_PROVIDER_CERTIFIED', 'AVAILABLE', 'VALID'].includes(normalized)) return 'success';
    if (['FAILED', 'FAIL', 'TIMED_OUT', 'CANCELLED', 'PROFILE_INVALID', 'UNMAPPED'].includes(normalized)) return 'danger';
    if (['BLOCKED', 'PARTIAL', 'AUTH_BLOCKED', 'PROFILE_UNAVAILABLE', 'FREEBUFF_HEADLESS_BLOCKED', 'BLOCKED_EXTERNAL_COMPATIBILITY', 'IN_PROGRESS', 'REVIEW'].includes(normalized)) return 'warning';
    if (['RUNNING', 'EXECUTING', 'READY', 'TRANSPORT_CERTIFIED', 'REAL'].includes(normalized)) return 'brand';
    return 'neutral';
  }

  function commandText(command) {
    if (Array.isArray(command)) return command.join(' ');
    return command ? String(command) : '—';
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
      system: { profiles: {}, context_policy: { roles: {} }, reasoning_policy: { escalation_policy: {} }, toolchain: {}, ui_vendor_lock: { packages: [] } },
      systemLoaded: false,
      taskDetail: { task: {}, definition: {}, requirements: [], context: null, validation: { commands: [], results: [], path_violations: [], missing_expected: [] }, git: { commits: [], changed_paths: [] }, attempts: [], events: [], telemetry: [] },
      goalDetail: { state: {}, summary: {}, goal_spec: { acceptance_criteria: [] }, plan: null, traceability: [], validation_results: [], final_audit: null },
      runDetail: { run: {}, goal_state: {}, tasks: [], traceability: [], validation_results: [], final_audit: null, metrics: {} },
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

      get projectName() { return this.snapshot?.factory?.project_name || 'Factory project'; },
      get factoryVersion() { return this.snapshot?.factory?.version || '—'; },
      get isActive() {
        if (this.snapshot?.factory?.active) return true;
        return (this.snapshot?.runs || []).some(run => ACTIVE_RUN_STATES.has(String(run.run_state || '').toUpperCase()));
      },
      get activeGoal() { return this.snapshot.active_goal || {}; },
      get hasActiveGoal() { return Boolean(this.snapshot.active_goal && this.snapshot.active_goal.goal_id); },
      get selectedRunLabel() { return this.snapshot.selected_run_id ? `Run ${this.snapshot.selected_run_id}` : 'No run selected'; },
      get boardColumns() { return this.snapshot?.board?.columns || []; },
      get providers() { return this.snapshot?.providers || []; },
      get goals() { return this.snapshot?.goals || []; },
      get runs() { return this.snapshot?.runs || []; },
      get metrics() { return this.snapshot?.metrics || {}; },
      get overviewMetrics() {
        return [
          { label: 'Tasks', value: numberOrDash(this.snapshot?.board?.task_count), hint: 'selected run' },
          { label: 'Running', value: numberOrDash(this.snapshot?.board?.counts?.RUNNING || 0), hint: 'active tasks' },
          { label: 'Blocked', value: numberOrDash(this.snapshot?.board?.counts?.BLOCKED || 0), hint: 'needs attention' },
          { label: 'Attempts', value: numberOrDash(this.metrics.attempts), hint: 'selected run' },
          { label: 'Context', value: bytesOrDash(this.metrics.context_bytes), hint: 'Factory-supplied' },
          { label: 'Input', value: numberOrDash(this.metrics.input_tokens), hint: 'provider-reported' },
          { label: 'Reasoning', value: numberOrDash(this.metrics.reasoning_tokens), hint: 'provider-reported' },
          { label: 'Duration', value: durationOrDash(this.metrics.duration_ms), hint: 'observed selected run' },
        ];
      },
      get goalCriteria() { return this.goalDetail.goal_spec?.acceptance_criteria || []; },
      get goalDetailTitle() { return (this.goalDetail.goal_spec && this.goalDetail.goal_spec.title) || this.goalDetail.state.goal_id || 'Goal'; },
      get goalAuditFindings() { return this.goalDetail.final_audit?.findings || []; },
      get runAuditVerdict() { const audit = this.runDetail.final_audit || {}; return audit.verdict || audit.status || 'recorded'; },
      get runAuditFindings() { return this.runDetail.final_audit?.findings || []; },
      get runRemediationRounds() { return this.runDetail.goal_state?.remediation_round_count ?? 0; },
      get goalTraceability() { return this.goalDetail.traceability || []; },
      get selectedRunTasks() { return this.runDetail.tasks || []; },
      get runTraceability() { return this.runDetail.traceability || []; },
      get runValidationResults() { return this.runDetail.validation_results || []; },
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
      get systemToolchain() {
        const lock = this.system.toolchain || {};
        return Object.keys(lock).sort().map(key => ({ key, value: this.toolchainLabel(lock[key]) }));
      },
      get uiVendorPackages() { return this.system?.ui_vendor_lock?.packages || []; },
      get selectedTask() { return this.taskDetail.task || {}; },
      get selectedTaskDefinition() { return this.taskDetail.definition || {}; },
      get selectedTaskRequirements() { return this.taskDetail.requirements || []; },
      get selectedTaskContext() { return this.taskDetail.context || {}; },
      get selectedTaskContextBudget() { return this.selectedTaskContext.budget || {}; },
      get selectedTaskIncludedFiles() { return this.selectedTaskContext.included_files || []; },
      get selectedTaskValidation() { return this.taskDetail.validation || { commands: [], results: [], path_violations: [], missing_expected: [] }; },
      get selectedTaskGit() { return this.taskDetail.git || { commits: [], changed_paths: [] }; },
      get selectedTaskAttempts() { return this.taskDetail.attempts || []; },
      get selectedTaskEvents() { return this.taskDetail.events || []; },
      get selectedTaskTelemetry() { return this.taskDetail.telemetry || []; },
      get hasTaskContext() { return Boolean(this.taskDetail.context && this.taskDetail.context.packet_id); },
      get reasoningPolicyVersion() { return this.system.reasoning_policy?.policy_version || '—'; },
      get reasoningPolicyStatus() { return this.system.reasoning_policy?.status || '—'; },
      get reasoningEscalationLimit() { return this.system.reasoning_policy?.escalation_policy?.max_effort_escalations_per_task ?? '—'; },

      pollDelay() {
        if (document.hidden) return 30000;
        return this.isActive ? 2000 : 8000;
      },

      reschedule(delay) {
        if (this.timer) window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => this.refresh(), delay === undefined ? this.pollDelay() : delay);
      },

      async request(path, options = {}) {
        const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options });
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
            cache: 'no-store', credentials: 'same-origin', headers, signal: this.requestController.signal,
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
        this.taskDetail = { task: {}, definition: {}, requirements: [], context: null, validation: { commands: [], results: [], path_violations: [], missing_expected: [] }, git: { commits: [], changed_paths: [] }, attempts: [], events: [], telemetry: [] };
        try {
          this.taskDetail = await this.request(`${API}/runs/${encodeURIComponent(task.run_id)}/tasks/${encodeURIComponent(task.task_id)}`);
        } catch (error) {
          this.error = error?.message || String(error);
          this.detailOpen = false;
        } finally {
          this.detailLoading = false;
        }
      },

      closeTask() { this.detailOpen = false; },

      async selectGoal(goal) {
        if (!goal?.goal_id) return;
        this.selectedGoalId = goal.goal_id;
        this.selectedDetailType = 'goal';
        this.goalDetail = { state: {}, summary: {}, goal_spec: { acceptance_criteria: [] }, plan: null, traceability: [], validation_results: [], final_audit: null };
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
        this.runDetail = { run: {}, tasks: [], traceability: [], validation_results: [], final_audit: null, metrics: {} };
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
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
          });
          this.notice = `Resume accepted (PID ${result.pid}).`;
          this.reschedule(500);
        } catch (error) {
          this.error = error?.message || String(error);
        }
      },

      clearNotice() { this.notice = ''; },
      yesNoUnknown(value) { return value === true ? 'yes' : (value === false ? 'no' : 'unknown'); },
      attemptDescriptor(attempt) { return [attempt?.profile_id || attempt?.worker_id, attempt?.model, attempt?.effort].filter(Boolean).join(' · '); },
      toolchainLabel(value) {
        if (value === null || value === undefined) return '—';
        if (typeof value !== 'object') return String(value);
        return value.version || value.installed_version || value.certified_version || value.status || value.compatibility_status || value.feasibility_status || JSON.stringify(value);
      },
      formatCommand: commandText,
      joinOrDash(value) { return Array.isArray(value) && value.length ? value.join(', ') : '—'; },
      percentageOrDash(value) { return value === null || value === undefined ? '—' : `${Math.round(Number(value) * 100)}%`; },
      taskDescriptor(task) { return [task?.profile_id || task?.worker_id, task?.model, task?.effort].filter(Boolean).join(' · '); },
      statusVariant,
      numberOrDash,
      bytesOrDash,
      durationOrDash,
      relativeTime,
    }));
  });
})();
