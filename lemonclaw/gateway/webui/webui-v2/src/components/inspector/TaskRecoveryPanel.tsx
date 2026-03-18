import { useEffect, useRef, useState } from 'preact/hooks';
import {
  activeOperatorTaskId,
  loadTaskDetail,
  loadOperatorQueue,
  type RecoveryHistoryEntry,
  loadTaskPanel,
  operatorQueueTasks,
  recoverySummary,
  recoveryTasks,
  sessionTasks,
  taskActionBusy,
  taskDetails,
  taskPanelError,
  type TaskStepRecord,
  triggerOutboxAbandon,
  triggerManualResume,
  triggerOutboxRetry,
  triggerSafeResume,
  triggerTaskRecheck,
  type TaskDisplayState,
  type TaskRecord,
} from '../../stores/tasks';
import { activeSessionKey } from '../../stores/sessions';
import { activeMemoryPanelTab, loadKnowledgeDocument } from '../../stores/knowledge';
import { t } from '../../stores/i18n';

function pillStyle(active = false) {
  return {
    padding: '4px 8px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(124, 58, 237, 0.1)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
  } as const;
}

function humanizeCode(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  return raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function openKnowledgeDetail(docId?: string | null) {
  if (!docId) return;
  activeMemoryPanelTab.value = 'detail';
  void loadKnowledgeDocument(docId);
}

function toneStyles(tone: string): { color: string; background: string; borderColor: string } {
  switch (tone) {
    case 'success':
      return { color: 'var(--success)', background: 'rgba(76, 175, 80, 0.12)', borderColor: 'rgba(76, 175, 80, 0.3)' };
    case 'warning':
      return { color: 'var(--accent)', background: 'rgba(255, 107, 53, 0.12)', borderColor: 'rgba(255, 107, 53, 0.28)' };
    case 'error':
      return { color: 'var(--error)', background: 'rgba(255, 68, 68, 0.12)', borderColor: 'rgba(255, 68, 68, 0.28)' };
    case 'accent':
      return { color: 'var(--teal)', background: 'rgba(10, 186, 181, 0.12)', borderColor: 'rgba(10, 186, 181, 0.28)' };
    default:
      return { color: 'var(--text-muted)', background: 'var(--bg-secondary)', borderColor: 'var(--border)' };
  }
}

function formatDisplayState(state?: TaskDisplayState | null): string {
  if (!state) return 'Unknown';
  const translated = t(`task_state_${state.key}` as any);
  return translated === `task_state_${state.key}` ? state.label : translated;
}

function formatDisplayDetail(state?: TaskDisplayState | null): string {
  if (!state) return '—';
  const translated = t(`task_state_detail_${state.key}` as any);
  return translated === `task_state_detail_${state.key}` ? (state.detail || '—') : translated;
}

function formatUpdatedAt(task: TaskRecord): string {
  const stamp = Number(task.updated_at_ms || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function suggestedActionLabel(candidate: Record<string, any> | null | undefined): string {
  const key = String(candidate?.recommended_action || '');
  if (!key) return t('task_action_run_safe_resume');
  const translated = t(`task_action_${key}` as any);
  return translated === `task_action_${key}` ? t('task_action_run_safe_resume') : translated;
}

function formatTaskStage(value?: string | null): string {
  const key = String(value || '').trim();
  if (!key) return '—';
  const translated = t(`task_state_${key}` as any);
  if (translated !== `task_state_${key}`) return translated;
  return humanizeCode(key);
}

function formatWorkflowSource(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const mapped: Record<string, string> = {
    operator_queue: 'operator queue',
    manual: 'manual action',
    trigger: 'automation',
    cron: 'scheduled run',
    session: 'chat',
  };
  return humanizeCode(mapped[raw] || raw);
}

function formatCandidateReason(candidate: Record<string, any> | null | undefined): string {
  if (!candidate) return '—';
  const action = String(candidate.recommended_action || '');
  const failedOutboxCount = Number(candidate.failed_outbox_count || 0);
  const replayableFailedCount = Number(candidate.replayable_failed_count || 0);
  const nonReplayableFailedCount = Number(candidate.non_replayable_failed_count || 0);
  switch (action) {
    case 'retry_outbox':
      return t('task_candidate_reason_retry_outbox').replace('{count}', String(failedOutboxCount));
    case 'replay_failed_steps':
      return t('task_candidate_reason_replay_failed_steps').replace('{count}', String(replayableFailedCount));
    case 'recheck':
      return t('task_candidate_reason_recheck');
    case 'wait_outbox':
      return t('task_candidate_reason_wait_outbox');
    case 'manual_resume':
      if (nonReplayableFailedCount > 0) {
        return t('task_candidate_reason_manual_resume_non_replayable').replace('{count}', String(nonReplayableFailedCount));
      }
      if (String(candidate.reason || '') === 'manual intervention required') {
        return t('task_candidate_reason_manual_intervention');
      }
      return String(candidate.reason || '—');
    case 'noop':
      return t('task_candidate_reason_noop');
    default:
      return String(candidate.reason || '—');
  }
}

function formatEventTime(value?: number | null): string {
  const stamp = Number(value || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function formatStepStatus(status?: string | null): string {
  const key = String(status || '').toLowerCase();
  const translated = t(`task_step_status_${key}` as any);
  return translated === `task_step_status_${key}` ? (status || 'unknown') : translated;
}

function formatRecoveryAction(action?: string | null): string {
  const key = String(action || '').toLowerCase();
  const translated = t(`task_recovery_action_${key}` as any);
  return translated === `task_recovery_action_${key}` ? (action || '—') : translated;
}

function stepTone(status?: string | null): { color: string; background: string; borderColor: string } {
  switch (String(status || '').toLowerCase()) {
    case 'completed':
      return toneStyles('success');
    case 'failed':
    case 'abandoned':
      return toneStyles('error');
    case 'waiting':
    case 'waiting_outbox':
    case 'retrying':
      return toneStyles('warning');
    case 'running':
    case 'pending':
      return toneStyles('accent');
    default:
      return toneStyles('muted');
  }
}

function isSettledTask(task: TaskRecord): boolean {
  return ['completed', 'abandoned'].includes(String(task.status || ''));
}

type LinkedFocus = {
  origin: 'step' | 'outbox' | 'recovery';
  stepIds: string[];
  outboxEventIds: string[];
  recoveryId?: string;
};

function sameLinkedFocus(a: LinkedFocus | null, b: LinkedFocus | null): boolean {
  return JSON.stringify(a || null) === JSON.stringify(b || null);
}

function makeStepFocus(step: TaskStepRecord): LinkedFocus {
  return {
    origin: 'step',
    stepIds: step.step_id ? [step.step_id] : [],
    outboxEventIds: [],
  };
}

function makeOutboxFocus(event: { event_id?: string; step_id?: string }): LinkedFocus {
  return {
    origin: 'outbox',
    stepIds: event.step_id ? [event.step_id] : [],
    outboxEventIds: event.event_id ? [event.event_id] : [],
  };
}

function makeRecoveryFocus(entry: RecoveryHistoryEntry): LinkedFocus {
  const ref = entry.ref || {};
  const stepIds = [ref.step_id, ...(ref.step_ids || [])].filter(Boolean) as string[];
  const outboxEventIds = [ref.outbox_event_id, ...(ref.outbox_event_ids || [])].filter(Boolean) as string[];
  return {
    origin: 'recovery',
    stepIds,
    outboxEventIds,
    recoveryId: entry.recovery_id,
  };
}

function linkedCardStyle(active: boolean) {
  if (!active) return {};
  return {
    borderColor: 'var(--teal)',
    boxShadow: '0 0 0 1px rgba(10, 186, 181, 0.35), inset 0 0 0 1px rgba(10, 186, 181, 0.12)',
    background: 'rgba(10, 186, 181, 0.06)',
  };
}

const summaryCardStyle = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '10px',
  display: 'grid',
  gap: '6px',
} as const;

const summaryLabelStyle = {
  fontSize: '10px',
  color: 'var(--text-muted)',
  fontFamily: 'var(--font-mono)',
  textTransform: 'uppercase',
  letterSpacing: '1px',
} as const;

const summaryDetailStyle = {
  fontSize: '11px',
  color: 'var(--text-secondary)',
  lineHeight: '1.45',
} as const;

function renderStepTimeline(
  steps: TaskStepRecord[] | undefined,
  linkedFocus: LinkedFocus | null,
  setLinkedFocus: (next: LinkedFocus | null) => void,
) {
  if (!steps || steps.length === 0) {
    return (
      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
        {t('task_steps_empty')}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {steps.map((step) => {
        const tone = stepTone(step.status);
        const focus = makeStepFocus(step);
        const isLinked = !!step.step_id && linkedFocus?.stepIds.includes(step.step_id);
        return (
          <div
            key={step.step_id}
            onClick={() => setLinkedFocus(sameLinkedFocus(linkedFocus, focus) ? null : focus)}
            style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-secondary)', padding: '8px 10px', display: 'grid', gap: '8px', cursor: 'pointer', ...linkedCardStyle(Boolean(isLinked)) }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>{step.name || step.step_id}</div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                  {step.step_type} · {step.step_id}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: '999px', border: '1px solid', fontSize: '10px', fontFamily: 'var(--font-mono)', ...tone }}>
                  {formatStepStatus(step.status)}
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: '999px', border: '1px solid var(--border)', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                  {step.replayable === false ? t('task_step_non_replayable') : t('task_step_replayable')}
                </span>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
              <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_step_started_at')}</div>
              <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(step.started_at_ms)}</div>
              <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_step_ended_at')}</div>
              <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(step.ended_at_ms)}</div>
            </div>
            {step.input_summary && (
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_step_input')}</div>
                <pre style={{ margin: 0, maxHeight: '120px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {step.input_summary}
                </pre>
              </div>
            )}
            {step.error && (
              <div style={{ fontSize: '11px', color: 'var(--error)', background: 'rgba(255, 68, 68, 0.08)', border: '1px solid rgba(255, 68, 68, 0.24)', borderRadius: '6px', padding: '8px 10px', lineHeight: '1.55', wordBreak: 'break-word' }}>
                {step.error}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function renderRecoveryHistory(
  history: RecoveryHistoryEntry[] | undefined,
  linkedFocus: LinkedFocus | null,
  setLinkedFocus: (next: LinkedFocus | null) => void,
  setExpandedOutboxId: (eventId: string | null) => void,
) {
  if (!history || history.length === 0) {
    return (
      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
        {t('task_recovery_history_empty')}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {history.slice().reverse().map((entry, idx) => (
        <div
          key={entry.recovery_id || `${entry.action || 'history'}-${entry.at_ms || idx}`}
          onClick={() => {
            const focus = makeRecoveryFocus(entry);
            const next = sameLinkedFocus(linkedFocus, focus) ? null : focus;
            setLinkedFocus(next);
            if (next && next.outboxEventIds.length === 1) {
              setExpandedOutboxId(next.outboxEventIds[0]);
            }
          }}
          style={{
            border: '1px solid var(--border)',
            borderRadius: '6px',
            background: 'var(--bg-secondary)',
            padding: '8px 10px',
            display: 'grid',
            gap: '8px',
            cursor: 'pointer',
            ...linkedCardStyle(Boolean(
              (!!entry.recovery_id && linkedFocus?.recoveryId === entry.recovery_id)
              || (!!entry.ref?.step_id && linkedFocus?.stepIds.includes(entry.ref.step_id))
              || ((entry.ref?.step_ids || []).some((id) => linkedFocus?.stepIds.includes(id)))
              || (!!entry.ref?.outbox_event_id && linkedFocus?.outboxEventIds.includes(entry.ref.outbox_event_id))
              || ((entry.ref?.outbox_event_ids || []).some((id) => linkedFocus?.outboxEventIds.includes(id)))
            )),
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                {formatRecoveryAction(entry.action)}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {(entry.source || '—')} · {formatEventTime(entry.at_ms)}
              </div>
            </div>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: '1.55', wordBreak: 'break-word' }}>
            {entry.reason || '—'}
          </div>
          {entry.details && Object.keys(entry.details).length > 0 && (
            <pre style={{ margin: 0, maxHeight: '140px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {JSON.stringify(entry.details, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

function formatResumeRoute(task: TaskRecord): string {
  const ctx = task.resume_context || {};
  const channel = ctx.channel || task.channel || '—';
  const chatId = ctx.chat_id || '—';
  const sessionKey = ctx.session_key || task.session_key || '—';
  return `${channel}:${chatId} · ${sessionKey}`;
}

function workflowNextStep(task: TaskRecord): string {
  const route = formatResumeRoute(task);
  const stateKey = task.display_state?.key || '';
  if (stateKey === 'resume_dispatch_failed') {
    return `${t('task_workflow_next_retry_dispatch')} ${route}`;
  }
  if (stateKey === 'resume_manual_only') {
    return `${t('task_workflow_next_manual_queue')} ${route}`;
  }
  if (stateKey === 'resume_requested') {
    return `${t('task_workflow_next_follow_queue')} ${route}`;
  }
  return `${t('task_workflow_next_review_outbox')} ${route}`;
}

function workflowInstruction(task: TaskRecord): string {
  const stateKey = task.display_state?.key || '';
  if (stateKey === 'resume_dispatch_failed') {
    return t('task_workflow_next_retry_dispatch');
  }
  if (stateKey === 'resume_manual_only') {
    return t('task_workflow_next_manual_queue');
  }
  if (stateKey === 'resume_requested') {
    return t('task_workflow_next_follow_queue');
  }
  return t('task_workflow_next_review_outbox');
}

function renderCountChips(counts: Record<string, number> | undefined, formatter: (key: string) => string) {
  const entries = Object.entries(counts || {}).filter(([, count]) => Number(count || 0) > 0);
  if (entries.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
      {entries.map(([key, count]) => (
        <span key={key} style={{ padding: '2px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px' }}>
          {formatter(key)} · {count}
        </span>
      ))}
    </div>
  );
}

function renderStringChips(values: string[] | undefined) {
  const entries = (values || []).filter(Boolean);
  if (entries.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
      {entries.map((value) => (
        <span key={value} style={{ padding: '2px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', maxWidth: '100%', wordBreak: 'break-all' }}>
          {value}
        </span>
      ))}
    </div>
  );
}

const SENSITIVE_COPY_KEY = /(^|[_-])(authorization|token|secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)($|[_-])/i;

function sanitizeForCopy(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeForCopy(item));
  }
  if (!value || typeof value !== 'object') {
    return value;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  return Object.fromEntries(
    entries.map(([key, nested]) => [
      key,
      SENSITIVE_COPY_KEY.test(key) ? '[redacted]' : sanitizeForCopy(nested),
    ]),
  );
}

function getTaskActionState(task: TaskRecord, detail: ReturnType<typeof taskDetails.peek>[string] | undefined) {
  const candidate = detail?.candidate;
  const state = task.display_state;
  const candidateAction = String(candidate?.recommended_action || '');
  const canRunSafeResume = Boolean(candidate?.safe_to_execute);
  const canRecheck = ['waiting', 'verifying'].includes(task.status || '') && (!candidate || candidate?.recommended_action === 'recheck');
  const isResumeLive = ['resume_requested', 'resume_queued', 'resume_running'].includes(state?.key || '');
  const showRetryDispatchCta = state?.key === 'resume_dispatch_failed' && canRunSafeResume && !isResumeLive;
  const showManualResumeCta = state?.key === 'resume_manual_only' && !isResumeLive;
  const showWorkflow = ['resume_requested', 'resume_dispatch_failed', 'resume_manual_only'].includes(state?.key || '');
  const showSuggestedAction = Boolean(
    candidate &&
    candidateAction &&
    candidateAction !== 'noop' &&
    !['completed', 'abandoned'].includes(task.status || '')
  );
  return { candidate, state, canRunSafeResume, canRecheck, isResumeLive, showRetryDispatchCta, showManualResumeCta, showWorkflow, showSuggestedAction };
}

function renderTaskDetailBody(
  task: TaskRecord,
  detail: NonNullable<ReturnType<typeof taskDetails.peek>[string]>,
  busy: string | undefined,
  expandedOutboxId: string | null,
  setExpandedOutboxId: (eventId: string | null) => void,
  linkedFocus: LinkedFocus | null,
  setLinkedFocus: (next: LinkedFocus | null) => void,
  copiedLabel: string | null,
  copyValue: (label: string, value: unknown) => Promise<void>,
  withTopDivider = true,
) {
  const { candidate, state, showRetryDispatchCta, showManualResumeCta, showWorkflow, showSuggestedAction } = getTaskActionState(task, detail);
  const recovery = task.metadata?.recovery || {};
  const retrieval = detail.summary?.retrieval || task.retrieval || task.metadata?.retrieval || null;
  const route = formatResumeRoute(task);
  const showResumeStats = Boolean(detail.summary?.last_successful_step || detail.summary?.resume_from_step);
  const summaryAction = showSuggestedAction && candidate ? suggestedActionLabel(candidate) : t('task_action_noop');
  const summaryReason = showSuggestedAction && candidate ? formatCandidateReason(candidate) : formatDisplayDetail(detail.summary?.display_state || state);
  const statusDetail = formatDisplayDetail(detail.summary?.display_state || state);
  const statusTone = toneStyles(state?.tone || 'muted');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', ...(withTopDivider ? { borderTop: '1px dashed var(--border)', paddingTop: '10px' } : {}) }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }}>
        <div style={summaryCardStyle}>
          <div style={summaryLabelStyle}>{t('task_current_status')}</div>
          <div style={{ fontSize: '12px', color: statusTone.color, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '7px', height: '7px', borderRadius: '999px', background: statusTone.color }} />
            {formatDisplayState(state)}
          </div>
          <div style={summaryDetailStyle}>{statusDetail}</div>
        </div>
        <div style={summaryCardStyle}>
          <div style={summaryLabelStyle}>{t('task_suggested_action')}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{summaryAction}</div>
          <div style={summaryDetailStyle}>{summaryReason}</div>
        </div>
        <div style={summaryCardStyle}>
          <div style={summaryLabelStyle}>{t('task_workflow_title')}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>{route}</div>
          <div style={summaryDetailStyle}>{workflowInstruction(task)}</div>
        </div>
      </div>
      {linkedFocus && (
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={() => setLinkedFocus(null)}
            style={{
              padding: '5px 8px',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              cursor: 'pointer',
            }}
          >
            {t('task_clear_focus')}
          </button>
        </div>
      )}
      {(detail.summary?.status_counts || detail.summary?.outbox_status_counts || detail.summary?.outbox_effect_type_counts || showResumeStats || detail.summary?.recovery_history) && (
        <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            {t('task_execution_snapshot')}
          </summary>
          <div style={{ display: 'grid', gap: '8px', marginTop: '10px' }}>
            {detail.summary?.status_counts && (
              <div style={{ display: 'grid', gap: '6px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  {t('task_step_status_summary')}
                </div>
                {renderCountChips(detail.summary.status_counts, formatStepStatus)}
              </div>
            )}
            {detail.summary?.outbox_status_counts && (
              <div style={{ display: 'grid', gap: '6px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  {t('task_outbox_status_summary')}
                </div>
                {renderCountChips(detail.summary.outbox_status_counts, (key) => key)}
              </div>
            )}
            {detail.summary?.outbox_effect_type_counts && (
              <div style={{ display: 'grid', gap: '6px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  {t('task_outbox_effect_summary')}
                </div>
                {renderCountChips(detail.summary.outbox_effect_type_counts, (key) => key)}
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                  {t('task_outbox_active_count')}: {detail.summary?.outbox_active_count ?? 0} · {t('task_outbox_terminal_count')}: {detail.summary?.outbox_terminal_count ?? 0}
                </div>
              </div>
            )}
            {showResumeStats && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>
                    {t('task_last_successful_step')}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                    {detail.summary?.last_successful_step || '—'}
                  </div>
                </div>
                <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>
                    {t('task_resume_from_step')}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                    {detail.summary?.resume_from_step || '—'}
                  </div>
                </div>
              </div>
            )}
          </div>
        </details>
      )}
      {retrieval && (
        <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            {t('task_retrieval_summary')}
          </summary>
          <div style={{ display: 'grid', gap: '6px', marginTop: '10px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_strategy')}</div>
            <div style={{ color: 'var(--text-primary)' }}>{String(retrieval.strategy || '—')}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_latency')}</div>
            <div style={{ color: 'var(--text-primary)' }}>{retrieval.latency_ms != null ? `${retrieval.latency_ms}ms` : '—'}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_fallbacks')}</div>
            <div style={{ color: 'var(--text-primary)' }}>{retrieval.fallback_count != null ? `${retrieval.fallback_count}` : '—'}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_hits')}</div>
            <div style={{ color: 'var(--text-primary)' }}>
              cards:{retrieval.card_count ?? 0} · rules:{retrieval.rule_count ?? 0} · knowledge:{retrieval.knowledge_count ?? 0}
            </div>
          </div>
          {renderStringChips(retrieval.hit_sources) && (
            <div style={{ display: 'grid', gap: '6px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_hit_sources')}</div>
              {renderStringChips(retrieval.hit_sources)}
            </div>
          )}
          {retrieval.card_hits && retrieval.card_hits.length > 0 && (
            <div style={{ display: 'grid', gap: '6px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_card_hits')}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {retrieval.card_hits.map((item: NonNullable<typeof retrieval.card_hits>[number], idx: number) => (
                  <div key={`${item.name || 'card'}-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', background: 'rgba(255,255,255,0.03)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>{item.name || '—'}</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>{item.source || '—'}</div>
                        {item.preview ? <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{item.preview}</div> : null}
                      </div>
                      {item.type ? <span style={pillStyle()}>{item.type}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {retrieval.rule_hits && retrieval.rule_hits.length > 0 && (
            <div style={{ display: 'grid', gap: '6px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_rule_hits')}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {retrieval.rule_hits.map((item: NonNullable<typeof retrieval.rule_hits>[number], idx: number) => (
                  <div key={`${item.trigger || 'rule'}-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', background: 'rgba(255,255,255,0.03)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word', marginBottom: '4px' }}>{item.trigger || '—'}</div>
                    {item.lesson ? <div style={{ fontSize: '11px', color: 'var(--text-secondary)', wordBreak: 'break-word', marginBottom: '4px' }}>{item.lesson}</div> : null}
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', wordBreak: 'break-word' }}>{item.action || '—'}</div>
                    {item.source ? <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px', wordBreak: 'break-all' }}>{item.source}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          )}
          {renderStringChips(retrieval.knowledge_sources) && (
            <div style={{ display: 'grid', gap: '6px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_knowledge_sources')}</div>
              {renderStringChips(retrieval.knowledge_sources)}
            </div>
          )}
          {retrieval.knowledge_hits && retrieval.knowledge_hits.length > 0 && (
            <div style={{ display: 'grid', gap: '6px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_retrieval_knowledge_hits')}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {retrieval.knowledge_hits.map((item: NonNullable<typeof retrieval.knowledge_hits>[number], idx: number) => (
                  <div
                    key={`${item.source || 'knowledge'}-${idx}`}
                    onClick={() => openKnowledgeDetail(item.doc_id)}
                    style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', background: 'rgba(255,255,255,0.03)', cursor: item.doc_id ? 'pointer' : 'default' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>{item.title || '—'}</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>{item.source || '—'}</div>
                      </div>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                        {item.doc_id ? (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              openKnowledgeDetail(item.doc_id);
                            }}
                            style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)', borderRadius: '4px', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}
                          >
                            {t('open')}
                          </button>
                        ) : null}
                        {item.page_label ? <span style={pillStyle()}>{item.page_label}</span> : null}
                        {item.result_type ? <span style={pillStyle()}>{item.result_type}</span> : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          </div>
        </details>
      )}
      {(showRetryDispatchCta || showManualResumeCta) && (
        <div style={{
          fontSize: '11px',
          lineHeight: '1.55',
          color: showRetryDispatchCta ? 'var(--error)' : 'var(--accent)',
          background: showRetryDispatchCta ? 'rgba(255, 68, 68, 0.08)' : 'rgba(255, 107, 53, 0.08)',
          border: '1px solid',
          borderColor: showRetryDispatchCta ? 'rgba(255, 68, 68, 0.24)' : 'rgba(255, 107, 53, 0.24)',
          borderRadius: '6px',
          padding: '8px 10px',
          fontFamily: 'var(--font-mono)',
        }}>
          {showRetryDispatchCta ? t('task_operator_cta_resume_dispatch_failed') : t('task_operator_cta_manual_resume_only')}
        </div>
      )}
      {showWorkflow && (
        <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            {t('task_workflow_title')}
          </summary>
          <div style={{ display: 'grid', gap: '8px', marginTop: '10px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_queued_by')}</div>
            <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{recovery.source || '—'}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_queued_at')}</div>
            <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(recovery.requested_at_ms || recovery.detected_at_ms)}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_next_step')}</div>
            <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{workflowNextStep(task)}</div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_route')}</div>
            <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{route}</div>
          </div>
          </div>
        </details>
      )}
      <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
          {t('task_steps_title')}
        </summary>
        <div style={{ marginTop: '10px' }}>
          {renderStepTimeline(detail.steps, linkedFocus, setLinkedFocus)}
        </div>
      </details>
      <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
          {t('task_recovery_history_title')}
        </summary>
        <div style={{ marginTop: '10px' }}>
          {renderRecoveryHistory(detail.summary?.recovery_history, linkedFocus, setLinkedFocus, setExpandedOutboxId)}
        </div>
      </details>
      <details style={{ ...summaryCardStyle, padding: '10px 12px' }}>
        <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
          {t('task_outbox_title')}
        </summary>
        <div style={{ marginTop: '10px' }}>
        {!detail.outboxEvents || detail.outboxEvents.length === 0 ? (
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{t('task_outbox_empty')}</div>
        ) : detail.outboxEvents.map((event) => {
          const isOutboxOpen = expandedOutboxId === event.event_id;
          const eventTone = toneStyles(
            event.status === 'failed' || event.status === 'expired'
              ? 'error'
              : event.status === 'sent'
                ? 'success'
                : event.status === 'retrying'
                  ? 'warning'
                  : event.status === 'abandoned'
                    ? 'muted'
                    : 'accent'
          );
          const outboxBusy = busy === `outbox:${event.event_id}`;
          const focus = makeOutboxFocus(event);
          const isLinked = (!!event.event_id && linkedFocus?.outboxEventIds.includes(event.event_id)) || (!!event.step_id && linkedFocus?.stepIds.includes(event.step_id));
          const canAbandon = ['pending', 'claimed', 'retrying', 'failed', 'expired'].includes(event.status || '');
          return (
            <div
              key={event.event_id}
              onClick={() => setLinkedFocus(sameLinkedFocus(linkedFocus, focus) ? null : focus)}
              style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-secondary)', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: '8px', cursor: 'pointer', ...linkedCardStyle(Boolean(isLinked)) }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                    {event.effect_type}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                    {event.event_id}
                  </div>
                </div>
                <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: '999px', border: '1px solid', fontSize: '10px', fontFamily: 'var(--font-mono)', ...eventTone }}>
                  {event.status}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  onClick={() => setExpandedOutboxId(isOutboxOpen ? null : event.event_id)}
                  style={{
                    padding: '5px 8px',
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    color: 'var(--text-secondary)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '10px',
                    cursor: 'pointer',
                  }}
                >
                  {isOutboxOpen ? t('task_outbox_hide') : t('task_outbox_show')}
                </button>
                {['failed', 'expired'].includes(event.status || '') && (
                  <button
                    onClick={() => triggerOutboxRetry(task.task_id, event.event_id)}
                    disabled={outboxBusy}
                    style={{
                      padding: '5px 8px',
                      background: 'transparent',
                      border: '1px solid var(--accent)',
                      borderRadius: '6px',
                      color: 'var(--accent)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      cursor: outboxBusy ? 'wait' : 'pointer',
                      opacity: outboxBusy ? 0.7 : 1,
                    }}
                  >
                    {outboxBusy ? t('task_action_running') : t('task_outbox_retry')}
                  </button>
                )}
                {canAbandon && (
                  <button
                    onClick={() => {
                      if (typeof window !== 'undefined' && !window.confirm(t('task_outbox_abandon_confirm'))) return;
                      void triggerOutboxAbandon(task.task_id, event.event_id, t('task_outbox_abandon_reason'));
                    }}
                    disabled={outboxBusy}
                    style={{
                      padding: '5px 8px',
                      background: 'transparent',
                      border: '1px solid rgba(255, 184, 77, 0.28)',
                      borderRadius: '6px',
                      color: 'var(--warning, #ffb84d)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      cursor: outboxBusy ? 'wait' : 'pointer',
                      opacity: outboxBusy ? 0.7 : 1,
                    }}
                  >
                    {outboxBusy ? t('task_action_running') : t('task_outbox_abandon')}
                  </button>
                )}
              </div>
              {isOutboxOpen && (
                <div style={{ display: 'grid', gap: '8px' }}>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <button
                      onClick={() => copyValue(`event:${event.event_id}`, event)}
                      style={{
                        padding: '5px 8px',
                        background: 'transparent',
                        border: '1px solid var(--border)',
                        borderRadius: '6px',
                        color: copiedLabel === `event:${event.event_id}` ? 'var(--success)' : 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '10px',
                        cursor: 'pointer',
                      }}
                    >
                      {copiedLabel === `event:${event.event_id}` ? t('task_copy_done') : t('task_copy_event_json')}
                    </button>
                    <button
                      onClick={() => copyValue(`payload:${event.event_id}`, event.payload || {})}
                      style={{
                        padding: '5px 8px',
                        background: 'transparent',
                        border: '1px solid var(--border)',
                        borderRadius: '6px',
                        color: copiedLabel === `payload:${event.event_id}` ? 'var(--success)' : 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '10px',
                        cursor: 'pointer',
                      }}
                    >
                      {copiedLabel === `payload:${event.event_id}` ? t('task_copy_done') : t('task_copy_payload')}
                    </button>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_effect')}</div>
                    <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                      {event.effect?.category || '—'} · {event.effect?.target_kind || '—'}
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_target')}</div>
                    <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{event.target || '—'}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_attempts')}</div>
                    <div style={{ color: 'var(--text-primary)' }}>{event.attempts ?? 0}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_step_id')}</div>
                    <div style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>{event.step_id || '—'}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_updated_at')}</div>
                    <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(event.updated_at_ms)}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_next_attempt')}</div>
                    <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(event.next_attempt_at_ms)}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_expires_at')}</div>
                    <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(event.expires_at_ms || event.lifecycle?.expires_at_ms)}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_terminal_at')}</div>
                    <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(event.terminal_at_ms || event.lifecycle?.terminal_at_ms)}</div>
                    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_error')}</div>
                    <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{event.error || '—'}</div>
                  </div>
                  {event.effect?.description ? (
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: '1.55' }}>
                      {event.effect.description}
                    </div>
                  ) : null}
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_outbox_last_result')}</div>
                    <pre style={{ margin: 0, maxHeight: '140px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {JSON.stringify(event.lifecycle?.last_delivery_result || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_outbox_history')}</div>
                    <pre style={{ margin: 0, maxHeight: '160px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {JSON.stringify(event.lifecycle?.delivery_history || [], null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_outbox_payload')}</div>
                    <pre style={{ margin: 0, maxHeight: '180px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {JSON.stringify(event.payload || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_outbox_metadata')}</div>
                    <pre style={{ margin: 0, maxHeight: '160px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {JSON.stringify(event.metadata || {}, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        </div>
      </details>
    </div>
  );
}

function taskCard(
  task: TaskRecord,
  expandedTaskId: string | null,
  setExpandedTaskId: (taskId: string | null) => void,
  expandedOutboxId: string | null,
  setExpandedOutboxId: (eventId: string | null) => void,
) {
  const isExpanded = expandedTaskId === task.task_id;
  const detail = taskDetails.value[task.task_id];
  const busy = taskActionBusy.value[task.task_id];
  const { candidate, state, canRunSafeResume, canRecheck, isResumeLive, showRetryDispatchCta, showManualResumeCta } = getTaskActionState(task, detail);
  const tone = toneStyles(state?.tone || 'muted');
  const route = formatResumeRoute(task);

  return (
    <div key={task.task_id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: '1.45', marginBottom: '6px', wordBreak: 'break-word' }}>
            {task.goal || task.task_id}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '2px 8px',
              borderRadius: '999px',
              border: '1px solid',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
              ...tone,
            }}>
              {state?.key === 'resume_running' && <span class="pulse-dot" style={{ background: tone.color }} />}
              {formatDisplayState(state)}
            </span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {formatTaskStage(task.current_stage)}
              </span>
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {t('task_updated_at')}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            {formatUpdatedAt(task)}
          </div>
        </div>
      </div>

      {state?.detail && (
        <div style={{
          fontSize: '11px',
          lineHeight: '1.55',
          color: tone.color,
          background: tone.background,
          border: '1px solid',
          borderColor: tone.borderColor,
          borderRadius: '6px',
          padding: '8px 10px',
          fontFamily: 'var(--font-mono)',
        }}>
          {formatDisplayDetail(state)}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {task.task_id}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', wordBreak: 'break-word' }}>
            {route}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={async () => {
              if (!isExpanded) await loadTaskDetail(task.task_id);
              setExpandedTaskId(isExpanded ? null : task.task_id);
            }}
            style={{
              padding: '6px 10px',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            {isExpanded ? t('task_hide_details') : t('task_show_details')}
          </button>
          {showManualResumeCta && (
            <button
              onClick={() => triggerManualResume(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                border: '1px solid var(--accent)',
                borderRadius: '6px',
                color: 'var(--accent)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'manual_resume' ? t('task_action_running') : t('task_action_queue_manual_resume')}
            </button>
          )}
          {canRunSafeResume && !isResumeLive && (
            <button
              onClick={() => triggerSafeResume(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'var(--accent)',
                border: '1px solid var(--accent)',
                borderRadius: '6px',
                color: '#fff',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'resume'
                ? t('task_action_running')
                : showRetryDispatchCta
                  ? t('task_action_retry_resume_dispatch')
                  : suggestedActionLabel(candidate)}
            </button>
          )}
          {canRecheck && !canRunSafeResume && !isResumeLive && (
            <button
              onClick={() => triggerTaskRecheck(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                border: '1px solid var(--teal)',
                borderRadius: '6px',
                color: 'var(--teal)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'recheck' ? t('task_action_running') : t('task_action_recheck')}
            </button>
          )}
        </div>
      </div>

    </div>
  );
}

function recoveryQueueCard(
  task: TaskRecord,
  expandedTaskId: string | null,
  setExpandedTaskId: (taskId: string | null) => void,
  expandedOutboxId: string | null,
  setExpandedOutboxId: (eventId: string | null) => void,
) {
  const isExpanded = expandedTaskId === task.task_id;
  const detail = taskDetails.value[task.task_id];
  const busy = taskActionBusy.value[task.task_id];
  const { candidate, state, canRunSafeResume, canRecheck, isResumeLive, showRetryDispatchCta, showManualResumeCta } = getTaskActionState(task, detail);
  const tone = toneStyles(state?.tone || 'warning');
  const queue = task.queue || {};

  return (
    <div key={`recovery-${task.task_id}`} style={{ background: tone.background, border: '1px solid', borderColor: tone.borderColor, borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: '1.45', marginBottom: '6px', wordBreak: 'break-word' }}>
            {task.goal || task.task_id}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: '999px', border: '1px solid', fontSize: '10px', fontFamily: 'var(--font-mono)', ...tone }}>
              {formatDisplayState(state)}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {formatTaskStage(queue.recommended_action || task.current_stage)}
            </span>
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {t('task_workflow_queued_at')}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            {formatEventTime(queue.queued_at_ms)}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_queued_by')}</div>
        <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{formatWorkflowSource(queue.source)}</div>
        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_route')}</div>
        <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{queue.route || formatResumeRoute(task)}</div>
        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_next_step')}</div>
        <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{workflowNextStep(task)}</div>
      </div>

      {queue.reason && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: '1.55', wordBreak: 'break-word' }}>
          {queue.reason}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {task.task_id}
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={async () => {
              if (!isExpanded) await loadTaskDetail(task.task_id);
              setExpandedTaskId(isExpanded ? null : task.task_id);
            }}
            style={{
              padding: '6px 10px',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            {isExpanded ? t('task_hide_details') : t('task_show_details')}
          </button>
          {showManualResumeCta && (
            <button
              onClick={() => triggerManualResume(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                border: '1px solid var(--accent)',
                borderRadius: '6px',
                color: 'var(--accent)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'manual_resume' ? t('task_action_running') : t('task_action_queue_manual_resume')}
            </button>
          )}
          {canRunSafeResume && !isResumeLive && (
            <button
              onClick={() => triggerSafeResume(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'var(--accent)',
                border: '1px solid var(--accent)',
                borderRadius: '6px',
                color: '#fff',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'resume'
                ? t('task_action_running')
                : showRetryDispatchCta
                  ? t('task_action_retry_resume_dispatch')
                  : suggestedActionLabel(candidate)}
            </button>
          )}
          {canRecheck && !canRunSafeResume && !isResumeLive && (
            <button
              onClick={() => triggerTaskRecheck(task.task_id)}
              disabled={!!busy}
              style={{
                padding: '6px 10px',
                background: 'transparent',
                border: '1px solid var(--teal)',
                borderRadius: '6px',
                color: 'var(--teal)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === 'recheck' ? t('task_action_running') : t('task_action_recheck')}
            </button>
          )}
        </div>
      </div>

    </div>
  );
}

export function TaskRecoveryPanel() {
  const [expandedOutboxId, setExpandedOutboxId] = useState<string | null>(null);
  const [linkedFocus, setLinkedFocus] = useState<LinkedFocus | null>(null);
  const [showSettledTasks, setShowSettledTasks] = useState(false);
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);
  const timerRef = useRef<any>(null);
  const expandedTaskId = activeOperatorTaskId.value;
  const setExpandedTaskId = (taskId: string | null) => {
    activeOperatorTaskId.value = taskId;
  };

  const actionableTasks = sessionTasks.value.filter((task) => !isSettledTask(task));
  const settledTasks = sessionTasks.value.filter((task) => isSettledTask(task));
  const recoveryQueueTasks = recoveryTasks.value.filter((task) => !sessionTasks.value.some((sessionTask) => sessionTask.task_id === task.task_id));
  const selectedTask = [...operatorQueueTasks.value, ...recoveryTasks.value, ...sessionTasks.value].find((task) => task.task_id === expandedTaskId) || null;
  const selectedDetail = expandedTaskId ? taskDetails.value[expandedTaskId] : null;
  const selectedBusy = expandedTaskId ? taskActionBusy.value[expandedTaskId] : undefined;
  const selectedState = selectedTask?.display_state;
  const selectedTone = toneStyles(selectedState?.tone || 'muted');

  useEffect(() => {
    loadTaskPanel(activeSessionKey.value);
  }, [activeSessionKey.value]);

  useEffect(() => {
    setLinkedFocus(null);
    setExpandedOutboxId(null);
  }, [expandedTaskId]);

  useEffect(() => {
    loadOperatorQueue();
  }, []);

  useEffect(() => {
    const startPolling = () => {
      if (timerRef.current) clearInterval(timerRef.current);
      const hasLive = [...sessionTasks.peek(), ...recoveryTasks.peek()].some((task) => {
        const key = task.display_state?.key || '';
        return ['resume_queued', 'resume_running', 'running', 'verifying', 'waiting_outbox'].includes(key) || task.status === 'running';
      });
      timerRef.current = setInterval(() => {
        if (document.visibilityState === 'visible') {
          loadTaskPanel(activeSessionKey.value).then(() => {
            const expanded = expandedTaskId;
            if (expanded) void loadTaskDetail(expanded);
          });
        }
      }, hasLive ? 4000 : 15000);
    };
    startPolling();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [activeSessionKey.value, expandedTaskId, sessionTasks.value.length, recoveryTasks.value.length]);

  const copyValue = async (label: string, value: unknown) => {
    try {
      const sanitized = typeof value === 'string' ? value : sanitizeForCopy(value ?? {});
      await navigator.clipboard.writeText(typeof sanitized === 'string' ? sanitized : JSON.stringify(sanitized, null, 2));
      setCopiedLabel(label);
      window.setTimeout(() => {
        setCopiedLabel((current) => (current === label ? null : current));
      }, 1500);
    } catch (err) {
      console.error('Failed to copy outbox detail', err);
    }
  };

  const exportTask = async (taskId: string, format: 'json' | 'md', mode: 'copy' | 'download') => {
    try {
      const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/export?format=${format}`, {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        throw new Error('Failed to export task');
      }
      const content = await res.text();
      const label = `${mode}:${format}:${taskId}`;
      if (mode === 'copy') {
        await navigator.clipboard.writeText(content);
        setCopiedLabel(label);
        window.setTimeout(() => {
          setCopiedLabel((current) => (current === label ? null : current));
        }, 1500);
        return;
      }
      const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/markdown;charset=utf-8' });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = `${taskId}.${format}`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      console.error('Failed to export task detail', err);
    }
  };

  const exportPostmortem = async (taskId: string, format: 'json' | 'md', mode: 'copy' | 'download') => {
    try {
      const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/postmortem?format=${format}`, {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        throw new Error('Failed to export task postmortem');
      }
      const content = await res.text();
      const label = `postmortem:${mode}:${format}:${taskId}`;
      if (mode === 'copy') {
        await navigator.clipboard.writeText(content);
        setCopiedLabel(label);
        window.setTimeout(() => {
          setCopiedLabel((current) => (current === label ? null : current));
        }, 1500);
        return;
      }
      const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/markdown;charset=utf-8' });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = `${taskId}.postmortem.${format}`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      console.error('Failed to export task postmortem', err);
    }
  };

  const exportBundle = async (taskId: string, format: 'json' | 'md', mode: 'copy' | 'download') => {
    try {
      const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/bundle?format=${format}`, {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        throw new Error('Failed to export task bundle');
      }
      const content = await res.text();
      const label = `bundle:${mode}:${format}:${taskId}`;
      if (mode === 'copy') {
        await navigator.clipboard.writeText(content);
        setCopiedLabel(label);
        window.setTimeout(() => {
          setCopiedLabel((current) => (current === label ? null : current));
        }, 1500);
        return;
      }
      const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/markdown;charset=utf-8' });
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = `${taskId}.bundle.${format}`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      console.error('Failed to export task bundle', err);
    }
  };

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--teal)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>// {t('tasks_panel_title')}</span>
        <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
          {sessionTasks.value.length} {t('tasks_panel_session_count')}
        </span>
      </div>

      {taskPanelError.value && (
        <div style={{ marginBottom: '12px', padding: '10px 12px', borderRadius: '6px', border: '1px solid rgba(255, 68, 68, 0.28)', background: 'rgba(255, 68, 68, 0.08)', color: 'var(--error)', fontFamily: 'var(--font-mono)', fontSize: '11px', lineHeight: 1.5 }}>
          {taskPanelError.value}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
        <div style={{ padding: '4px 10px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-secondary)' }}>
          {t('tasks_panel_session_count')}: {sessionTasks.value.length}
        </div>
        <div style={{ padding: '4px 10px', borderRadius: '999px', border: '1px solid rgba(10, 186, 181, 0.24)', background: 'rgba(10, 186, 181, 0.08)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--teal)' }}>
          {t('tasks_panel_actionable_count')}: {actionableTasks.length}
        </div>
        <div style={{ padding: '4px 10px', borderRadius: '999px', border: '1px solid rgba(255, 107, 53, 0.28)', background: 'rgba(255, 107, 53, 0.1)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent)' }}>
          {t('tasks_panel_manual_review_count')}: {recoverySummary.value?.manual_review_required || 0}
        </div>
        <div style={{ padding: '4px 10px', borderRadius: '999px', border: '1px solid rgba(76, 175, 80, 0.24)', background: 'rgba(76, 175, 80, 0.08)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--success)' }}>
          {t('tasks_panel_settled_count')}: {settledTasks.length}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {sessionTasks.value.length === 0 ? (
          <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('tasks_panel_empty')}</div>
          </div>
        ) : (
          <>
            {actionableTasks.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--teal)', textTransform: 'uppercase', letterSpacing: '1.2px' }}>
                  {t('tasks_panel_actionable')}
                </div>
                {actionableTasks.map((task) => taskCard(task, expandedTaskId, setExpandedTaskId, expandedOutboxId, setExpandedOutboxId))}
              </div>
            )}

            {settledTasks.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.2px' }}>
                    {t('tasks_panel_settled')}
                  </div>
                  <button
                    onClick={() => setShowSettledTasks(!showSettledTasks)}
                    style={{
                      padding: '5px 8px',
                      background: 'transparent',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      color: 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '10px',
                      cursor: 'pointer',
                    }}
                  >
                    {showSettledTasks ? t('tasks_panel_hide_settled') : t('tasks_panel_show_settled')}
                  </button>
                </div>
                {showSettledTasks && settledTasks.map((task) => taskCard(task, expandedTaskId, setExpandedTaskId, expandedOutboxId, setExpandedOutboxId))}
              </div>
            )}
          </>
        )}

        {recoveryTasks.value.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.2px', marginTop: '4px' }}>
              {t('tasks_panel_manual_review')}
            </div>
            {recoveryQueueTasks.length === 0 ? (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{t('tasks_panel_manual_review_in_session')}</div>
            ) : (
              recoveryQueueTasks.map((task) => recoveryQueueCard(task, expandedTaskId, setExpandedTaskId, expandedOutboxId, setExpandedOutboxId))
            )}
          </div>
        )}

        {selectedTask && selectedDetail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-primary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px' }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--teal)', textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: '6px' }}>
                  {t('task_detail_panel_title')}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: '1.45', marginBottom: '6px', wordBreak: 'break-word' }}>
                  {selectedTask.goal || selectedTask.task_id}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '2px 8px', borderRadius: '999px', border: '1px solid', fontSize: '10px', fontFamily: 'var(--font-mono)', ...selectedTone }}>
                    {formatDisplayState(selectedState)}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {formatResumeRoute(selectedTask)}
                  </span>
                </div>
              </div>
              <button
                onClick={() => setExpandedTaskId(null)}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {t('task_detail_panel_close')}
              </button>
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                onClick={() => exportTask(selectedTask.task_id, 'md', 'copy')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: copiedLabel === `copy:md:${selectedTask.task_id}` ? 'var(--success)' : 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {copiedLabel === `copy:md:${selectedTask.task_id}` ? t('task_copy_done') : t('task_export_summary')}
              </button>
              <button
                onClick={() => exportTask(selectedTask.task_id, 'json', 'download')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {t('task_export_json')}
              </button>
              <button
                onClick={() => exportBundle(selectedTask.task_id, 'md', 'copy')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: copiedLabel === `bundle:copy:md:${selectedTask.task_id}` ? 'var(--success)' : 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {copiedLabel === `bundle:copy:md:${selectedTask.task_id}` ? t('task_copy_done') : t('task_export_bundle_copy')}
              </button>
              <button
                onClick={() => exportBundle(selectedTask.task_id, 'json', 'download')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {t('task_export_bundle_json')}
              </button>
              <button
                onClick={() => exportPostmortem(selectedTask.task_id, 'md', 'copy')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: copiedLabel === `postmortem:copy:md:${selectedTask.task_id}` ? 'var(--success)' : 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {copiedLabel === `postmortem:copy:md:${selectedTask.task_id}` ? t('task_copy_done') : t('task_export_postmortem_copy')}
              </button>
              <button
                onClick={() => exportPostmortem(selectedTask.task_id, 'json', 'download')}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {t('task_export_postmortem_json')}
              </button>
            </div>
            {renderTaskDetailBody(selectedTask, selectedDetail, selectedBusy, expandedOutboxId, setExpandedOutboxId, linkedFocus, setLinkedFocus, copiedLabel, copyValue, false)}
          </div>
        )}
      </div>
    </div>
  );
}
