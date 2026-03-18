import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';
import { activeSessionKey } from './sessions';

export interface TaskDisplayState {
  key: string;
  label: string;
  tone: 'accent' | 'warning' | 'success' | 'error' | 'muted' | string;
  detail?: string;
}

export interface RecoveryHistoryEntry {
  recovery_id?: string;
  source?: string;
  action?: string;
  reason?: string;
  details?: Record<string, any>;
  at_ms?: number;
  ref?: {
    step_id?: string;
    outbox_event_id?: string;
    step_ids?: string[];
    outbox_event_ids?: string[];
  };
}

export interface TaskStepRecord {
  step_id: string;
  step_type: string;
  name: string;
  status: string;
  started_at_ms?: number;
  ended_at_ms?: number | null;
  input_summary?: string;
  error?: string | null;
  replayable?: boolean;
}

export interface RetrievalMeta {
  strategy?: string;
  latency_ms?: number;
  fallback_count?: number;
  fallbacks?: string[];
  card_count?: number;
  rule_count?: number;
  card_hits?: Array<{
    name?: string;
    type?: string;
    source?: string;
    preview?: string;
  }>;
  rule_hits?: Array<{
    trigger?: string;
    lesson?: string;
    action?: string;
    source?: string;
  }>;
  knowledge_count?: number;
  knowledge_sources?: string[];
  knowledge_hits?: Array<{
    doc_id?: string;
    title?: string;
    source?: string;
    result_type?: string;
    page_label?: string;
  }>;
  hit_sources?: string[];
  card_sources?: Record<string, string>;
  rule_sources?: Record<string, string>;
}

export interface TaskSummary {
  step_count?: number;
  status_counts?: Record<string, number>;
  last_successful_step?: string | null;
  resume_from_step?: string | null;
  display_state?: TaskDisplayState;
  outbox_count?: number;
  outbox_status_counts?: Record<string, number>;
  outbox_effect_type_counts?: Record<string, number>;
  outbox_active_count?: number;
  outbox_terminal_count?: number;
  recovery_history?: RecoveryHistoryEntry[];
  retrieval?: RetrievalMeta;
}

export interface OutboxEventRecord {
  event_id: string;
  task_id: string;
  step_id: string;
  effect_type: string;
  effect?: {
    effect_type?: string;
    category?: string;
    target_kind?: string;
    description?: string;
  };
  target: string;
  status: string;
  attempts?: number;
  next_attempt_at_ms?: number | null;
  expires_at_ms?: number | null;
  terminal_at_ms?: number | null;
  error?: string | null;
  payload?: Record<string, any>;
  metadata?: Record<string, any>;
  lifecycle?: {
    active?: boolean;
    terminal?: boolean;
    terminal_kind?: string;
    next_attempt_at_ms?: number | null;
    expires_at_ms?: number | null;
    terminal_at_ms?: number | null;
    last_delivery_result?: Record<string, any>;
    delivery_history?: Array<Record<string, any>>;
  };
  updated_at_ms?: number;
}

export interface TaskRecord {
  task_id: string;
  session_key: string;
  agent_id: string;
  mode: string;
  channel: string;
  goal: string;
  status: string;
  current_stage: string;
  updated_at_ms?: number;
  resume_from_step?: string | null;
  display_state?: TaskDisplayState;
  resume_context?: Record<string, any>;
  metadata?: Record<string, any>;
  retrieval?: RetrievalMeta;
  queue?: {
    queued_at_ms?: number;
    source?: string;
    reason?: string;
    manual_review_required?: boolean;
    recommended_action?: string;
    safe_to_execute?: boolean;
    failed_outbox_count?: number;
    last_successful_step?: string;
    route?: string;
    next_step?: string;
  };
}

export interface TaskDetail {
  task: TaskRecord;
  summary?: TaskSummary;
  steps?: TaskStepRecord[];
  outboxEvents?: OutboxEventRecord[];
  candidate?: Record<string, any> | null;
}

export const sessionTasks = signal<TaskRecord[]>([]);
export const recoverySummary = signal<Record<string, number> | null>(null);
export const recoveryTasks = signal<TaskRecord[]>([]);
export const operatorQueueTasks = signal<TaskRecord[]>([]);
export const taskDetails = signal<Record<string, TaskDetail>>({});
export const taskPanelError = signal<string | null>(null);
export const taskActionBusy = signal<Record<string, string>>({});
export const activeOperatorTaskId = signal<string | null>(null);

function setTaskBusy(taskId: string, action: string | null) {
  const next = { ...taskActionBusy.peek() };
  if (action) next[taskId] = action;
  else delete next[taskId];
  taskActionBusy.value = next;
}

function mergeTaskDetail(taskId: string, patch: Partial<TaskDetail>) {
  const current = taskDetails.peek();
  taskDetails.value = {
    ...current,
    [taskId]: {
      ...(current[taskId] || { task: { task_id: taskId } as TaskRecord }),
      ...patch,
    },
  };
}

export async function loadTaskPanel(sessionKey = activeSessionKey.value) {
  taskPanelError.value = null;
  try {
    const [tasksRes, recoveryRes] = await Promise.all([
      apiFetch(`/api/tasks?limit=12${sessionKey ? `&session_key=${encodeURIComponent(sessionKey)}` : ''}`),
      apiFetch('/api/operator-queue?limit=8&manual_review_only=true'),
    ]);
    const tasksData = await tasksRes.json();
    const recoveryData = await recoveryRes.json();
    sessionTasks.value = tasksData.tasks || [];
    recoverySummary.value = recoveryData.summary || null;
    recoveryTasks.value = recoveryData.tasks || [];
  } catch (err: any) {
    console.error('Failed to load task panel', err);
    taskPanelError.value = err?.message || 'Failed to load task state';
  }
}

export async function loadOperatorQueue() {
  taskPanelError.value = null;
  try {
    const res = await apiFetch('/api/operator-queue?limit=24');
    const data = await res.json();
    operatorQueueTasks.value = data.tasks || [];
  } catch (err: any) {
    console.error('Failed to load operator queue', err);
    taskPanelError.value = err?.message || 'Failed to load operator queue';
  }
}

export async function loadTaskDetail(taskId: string) {
  try {
    const [taskRes, candidateRes, outboxRes] = await Promise.all([
      apiFetch(`/api/tasks/${encodeURIComponent(taskId)}`),
      apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/resume-candidate`, { silent404: true }),
      apiFetch(`/api/outbox?task_id=${encodeURIComponent(taskId)}&limit=50`, { silent404: true }),
    ]);
    const taskData = await taskRes.json();
    let candidate: Record<string, any> | null = null;
    if (candidateRes.ok) {
      const candidateData = await candidateRes.json();
      candidate = candidateData.candidate || null;
    }
    let outboxEvents: OutboxEventRecord[] = [];
    if (outboxRes.ok) {
      const outboxData = await outboxRes.json();
      outboxEvents = outboxData.events || [];
    }
    mergeTaskDetail(taskId, {
      task: taskData.task,
      summary: taskData.summary,
      steps: taskData.steps || [],
      outboxEvents,
      candidate,
    });
  } catch (err: any) {
    console.error('Failed to load task detail', err);
    taskPanelError.value = err?.message || 'Failed to load task detail';
  }
}

export async function triggerSafeResume(taskId: string) {
  setTaskBusy(taskId, 'resume');
  taskPanelError.value = null;
  try {
    await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/resume/execute`, { method: 'POST' });
    await Promise.all([loadTaskPanel(), loadTaskDetail(taskId)]);
  } catch (err: any) {
    console.error('Failed to execute safe resume', err);
    taskPanelError.value = err?.message || 'Failed to execute safe resume';
  } finally {
    setTaskBusy(taskId, null);
  }
}

export async function triggerTaskRecheck(taskId: string) {
  setTaskBusy(taskId, 'recheck');
  taskPanelError.value = null;
  try {
    await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/recheck`, { method: 'POST' });
    await Promise.all([loadTaskPanel(), loadTaskDetail(taskId)]);
  } catch (err: any) {
    console.error('Failed to recheck task', err);
    taskPanelError.value = err?.message || 'Failed to recheck task';
  } finally {
    setTaskBusy(taskId, null);
  }
}

export async function triggerManualResume(taskId: string) {
  setTaskBusy(taskId, 'manual_resume');
  taskPanelError.value = null;
  try {
    await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/resume`, { method: 'POST' });
    await Promise.all([loadTaskPanel(), loadTaskDetail(taskId)]);
  } catch (err: any) {
    console.error('Failed to request manual resume', err);
    taskPanelError.value = err?.message || 'Failed to queue manual resume';
  } finally {
    setTaskBusy(taskId, null);
  }
}

export async function triggerOutboxRetry(taskId: string, eventId: string) {
  setTaskBusy(taskId, `outbox:${eventId}`);
  taskPanelError.value = null;
  try {
    await apiFetch(`/api/outbox/${encodeURIComponent(eventId)}/retry`, { method: 'POST' });
    await Promise.all([loadTaskPanel(), loadTaskDetail(taskId)]);
  } catch (err: any) {
    console.error('Failed to retry outbox event', err);
    taskPanelError.value = err?.message || 'Failed to retry outbox event';
  } finally {
    setTaskBusy(taskId, null);
  }
}

export async function triggerOutboxAbandon(taskId: string, eventId: string, reason: string) {
  setTaskBusy(taskId, `outbox:${eventId}`);
  taskPanelError.value = null;
  try {
    await apiFetch(`/api/outbox/${encodeURIComponent(eventId)}/abandon`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
    await Promise.all([loadTaskPanel(), loadTaskDetail(taskId)]);
  } catch (err: any) {
    console.error('Failed to abandon outbox event', err);
    taskPanelError.value = err?.message || 'Failed to abandon outbox event';
  } finally {
    setTaskBusy(taskId, null);
  }
}
