import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';
import { activeSessionKey } from './sessions';

export interface TaskDisplayState {
  key: string;
  label: string;
  tone: 'accent' | 'warning' | 'success' | 'error' | 'muted' | string;
  detail?: string;
}

export interface OutboxEventRecord {
  event_id: string;
  task_id: string;
  step_id: string;
  effect_type: string;
  target: string;
  status: string;
  attempts?: number;
  next_attempt_at_ms?: number | null;
  error?: string | null;
  payload?: Record<string, any>;
  metadata?: Record<string, any>;
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
}

export interface TaskDetail {
  task: TaskRecord;
  summary?: Record<string, any>;
  steps?: Array<Record<string, any>>;
  outboxEvents?: OutboxEventRecord[];
  candidate?: Record<string, any> | null;
}

export const sessionTasks = signal<TaskRecord[]>([]);
export const recoverySummary = signal<Record<string, number> | null>(null);
export const recoveryTasks = signal<TaskRecord[]>([]);
export const taskDetails = signal<Record<string, TaskDetail>>({});
export const taskPanelError = signal<string | null>(null);
export const taskActionBusy = signal<Record<string, string>>({});

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
      apiFetch('/api/recovery?limit=8&manual_review_only=true'),
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
