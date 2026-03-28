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
  structured?: {
    session_summary?: string;
    fact_slots?: Array<{
      name?: string;
      type?: string;
      summary?: string;
    }>;
    retrieval_objects?: Array<{
      kind?: string;
      id?: string;
      title?: string;
      source?: string;
    }>;
  };
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

export interface TaskOperatorSummary {
  tone: TaskDisplayState['tone'];
  titleKey: string;
  bodyKey: string;
  actionKey?: string | null;
}

export interface StructuredMemoryWorkSurface {
  sourceTaskId: string;
  sourceGoal: string;
  sourceUpdatedAtMs?: number;
  sourceDisplayState?: TaskDisplayState | null;
  strategy?: string;
  latencyMs?: number;
  sessionSummary: string;
  factSlots: NonNullable<NonNullable<RetrievalMeta['structured']>['fact_slots']>;
  retrievalObjects: NonNullable<NonNullable<RetrievalMeta['structured']>['retrieval_objects']>;
  cardHits: NonNullable<NonNullable<RetrievalMeta['card_hits']>>;
  ruleHits: NonNullable<NonNullable<RetrievalMeta['rule_hits']>>;
  knowledgeHits: NonNullable<NonNullable<RetrievalMeta['knowledge_hits']>>;
  fallbackCount: number;
  fallbacks: string[];
  hitSources: string[];
  pipeline: StructuredMemoryPipelineView;
}

export interface StructuredMemoryPipelineView {
  search: {
    active: boolean;
    strategy?: string;
    hitSources: string[];
    cardCount: number;
    ruleCount: number;
    knowledgeCount: number;
    totalHits: number;
  };
  fetch: {
    active: boolean;
    cardHitCount: number;
    ruleHitCount: number;
    knowledgeHitCount: number;
    totalFetched: number;
  };
  summarize: {
    active: boolean;
    hasSessionSummary: boolean;
    factSlotCount: number;
    retrievalObjectCount: number;
  };
  failsoft: {
    active: boolean;
    fallbackCount: number;
    fallbacks: string[];
  };
}

function resolveTaskRetrieval(task: TaskRecord, detail?: TaskDetail | null): RetrievalMeta | null {
  return (
    detail?.summary?.retrieval
    || detail?.task?.retrieval
    || task.retrieval
    || (task.metadata?.retrieval as RetrievalMeta | undefined)
    || null
  );
}

function hasStructuredMemoryPayload(retrieval: RetrievalMeta | null | undefined): boolean {
  const structured = retrieval?.structured;
  return Boolean(
    structured?.session_summary
    || structured?.fact_slots?.length
    || structured?.retrieval_objects?.length
    || retrieval?.fallback_count
    || retrieval?.fallbacks?.length
    || retrieval?.hit_sources?.length
  );
}

function buildStructuredMemoryPipeline(retrieval: RetrievalMeta): StructuredMemoryPipelineView {
  const structured = retrieval.structured || {};
  const cardCount = Number(retrieval.card_count || 0);
  const ruleCount = Number(retrieval.rule_count || 0);
  const knowledgeCount = Number(retrieval.knowledge_count || 0);
  const cardHitCount = (retrieval.card_hits || []).length;
  const ruleHitCount = (retrieval.rule_hits || []).length;
  const knowledgeHitCount = (retrieval.knowledge_hits || []).length;
  const factSlotCount = (structured.fact_slots || []).length;
  const retrievalObjectCount = (structured.retrieval_objects || []).length;
  const sessionSummary = String(structured.session_summary || '').trim();
  const fallbacks = (retrieval.fallbacks || []).filter(Boolean);

  return {
    search: {
      active: Boolean(retrieval.strategy || retrieval.hit_sources?.length || cardCount || ruleCount || knowledgeCount),
      strategy: retrieval.strategy,
      hitSources: (retrieval.hit_sources || []).filter(Boolean),
      cardCount,
      ruleCount,
      knowledgeCount,
      totalHits: cardCount + ruleCount + knowledgeCount,
    },
    fetch: {
      active: Boolean(cardHitCount || ruleHitCount || knowledgeHitCount),
      cardHitCount,
      ruleHitCount,
      knowledgeHitCount,
      totalFetched: cardHitCount + ruleHitCount + knowledgeHitCount,
    },
    summarize: {
      active: Boolean(sessionSummary || factSlotCount || retrievalObjectCount),
      hasSessionSummary: Boolean(sessionSummary),
      factSlotCount,
      retrievalObjectCount,
    },
    failsoft: {
      active: Boolean(fallbacks.length || Number(retrieval.fallback_count || 0)),
      fallbackCount: Number(retrieval.fallback_count || 0),
      fallbacks,
    },
  };
}

export function buildStructuredMemoryWorkSurface(
  tasks: TaskRecord[],
  detailsById: Record<string, TaskDetail | undefined>,
): StructuredMemoryWorkSurface | null {
  const sorted = [...tasks].sort((a, b) => Number(b.updated_at_ms || 0) - Number(a.updated_at_ms || 0));
  const candidate = sorted.find((task) => hasStructuredMemoryPayload(resolveTaskRetrieval(task, detailsById[task.task_id])));
  if (!candidate) {
    return null;
  }
  const detail = detailsById[candidate.task_id];
  const retrieval = resolveTaskRetrieval(candidate, detail);
  if (!retrieval) {
    return null;
  }
  const structured = retrieval.structured || {};
  return {
    sourceTaskId: candidate.task_id,
    sourceGoal: candidate.goal || candidate.task_id,
    sourceUpdatedAtMs: candidate.updated_at_ms,
    sourceDisplayState: detail?.summary?.display_state || candidate.display_state || null,
    strategy: retrieval.strategy,
    latencyMs: retrieval.latency_ms,
    sessionSummary: String(structured.session_summary || '').trim(),
    factSlots: structured.fact_slots || [],
    retrievalObjects: structured.retrieval_objects || [],
    cardHits: retrieval.card_hits || [],
    ruleHits: retrieval.rule_hits || [],
    knowledgeHits: retrieval.knowledge_hits || [],
    fallbackCount: Number(retrieval.fallback_count || 0),
    fallbacks: (retrieval.fallbacks || []).filter(Boolean),
    hitSources: (retrieval.hit_sources || []).filter(Boolean),
    pipeline: buildStructuredMemoryPipeline(retrieval),
  };
}

function getTaskStateKey(task: TaskRecord) {
  return String(task.display_state?.key || task.status || '').trim().toLowerCase();
}

export function summarizeTaskOperatorState(task: TaskRecord, detail?: TaskDetail | null): TaskOperatorSummary {
  const stateKey = getTaskStateKey(task);
  const candidate = detail?.candidate || null;
  const summary = detail?.summary || null;
  const outboxActiveCount = Number(summary?.outbox_active_count || 0);
  const isResumeLive = ['resume_requested', 'resume_queued', 'resume_running'].includes(stateKey);

  if (stateKey === 'resume_dispatch_failed') {
    return {
      tone: 'warning',
      titleKey: 'task_operator_summary_dispatch_failed_title',
      bodyKey: 'task_operator_summary_dispatch_failed_body',
      actionKey: 'task_action_retry_resume_dispatch',
    };
  }

  if (stateKey === 'resume_manual_only' || task.queue?.manual_review_required) {
    return {
      tone: 'warning',
      titleKey: 'task_operator_summary_manual_help_title',
      bodyKey: 'task_operator_summary_manual_help_body',
      actionKey: 'task_action_queue_manual_resume',
    };
  }

  if (candidate?.safe_to_execute && !isResumeLive) {
    return {
      tone: 'accent',
      titleKey: 'task_operator_summary_continue_ready_title',
      bodyKey: 'task_operator_summary_continue_ready_body',
      actionKey: 'task_action_run_safe_resume',
    };
  }

  if (stateKey === 'verifying' || stateKey === 'waiting') {
    return {
      tone: 'muted',
      titleKey: 'task_operator_summary_checking_title',
      bodyKey: 'task_operator_summary_checking_body',
      actionKey: candidate?.recommended_action === 'recheck' ? 'task_action_recheck' : null,
    };
  }

  if (stateKey === 'waiting_outbox' || outboxActiveCount > 0) {
    return {
      tone: 'warning',
      titleKey: 'task_operator_summary_delivery_title',
      bodyKey: 'task_operator_summary_delivery_body',
      actionKey: candidate?.recommended_action === 'retry_outbox' ? 'task_action_retry_outbox' : null,
    };
  }

  if (task.status === 'running' || stateKey === 'running') {
    return {
      tone: 'accent',
      titleKey: 'task_operator_summary_running_title',
      bodyKey: 'task_operator_summary_running_body',
      actionKey: null,
    };
  }

  if (stateKey === 'completed') {
    return {
      tone: 'success',
      titleKey: 'task_operator_summary_completed_title',
      bodyKey: 'task_operator_summary_completed_body',
      actionKey: null,
    };
  }

  if (stateKey === 'abandoned' || task.status === 'abandoned') {
    return {
      tone: 'muted',
      titleKey: 'task_operator_summary_superseded_title',
      bodyKey: 'task_operator_summary_superseded_body',
      actionKey: null,
    };
  }

  return {
    tone: task.display_state?.tone || 'muted',
    titleKey: 'task_operator_summary_attention_title',
    bodyKey: 'task_operator_summary_attention_body',
    actionKey: candidate?.recommended_action ? `task_action_${candidate.recommended_action}` : null,
  };
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
