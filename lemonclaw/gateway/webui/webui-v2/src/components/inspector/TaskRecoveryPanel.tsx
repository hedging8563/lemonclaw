import { useEffect, useRef, useState } from 'preact/hooks';
import {
  loadTaskDetail,
  loadTaskPanel,
  recoverySummary,
  recoveryTasks,
  sessionTasks,
  taskActionBusy,
  taskDetails,
  taskPanelError,
  triggerManualResume,
  triggerOutboxRetry,
  triggerSafeResume,
  triggerTaskRecheck,
  type TaskDisplayState,
  type TaskRecord,
} from '../../stores/tasks';
import { activeSessionKey } from '../../stores/sessions';
import { t } from '../../stores/i18n';

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

function formatEventTime(value?: number | null): string {
  const stamp = Number(value || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
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

function taskCard(
  task: TaskRecord,
  expandedTaskId: string | null,
  setExpandedTaskId: (taskId: string | null) => void,
  expandedOutboxId: string | null,
  setExpandedOutboxId: (eventId: string | null) => void,
) {
  const isExpanded = expandedTaskId === task.task_id;
  const detail = taskDetails.value[task.task_id];
  const candidate = detail?.candidate;
  const busy = taskActionBusy.value[task.task_id];
  const state = task.display_state;
  const tone = toneStyles(state?.tone || 'muted');
  const recovery = task.metadata?.recovery || {};

  const canRunSafeResume = Boolean(candidate?.safe_to_execute);
  const canRecheck = ['waiting', 'verifying'].includes(task.status || '') && (!candidate || candidate?.recommended_action === 'recheck');
  const isResumeLive = ['resume_requested', 'resume_queued', 'resume_running'].includes(state?.key || '');
  const showRetryDispatchCta = state?.key === 'resume_dispatch_failed' && canRunSafeResume && !isResumeLive;
  const showManualResumeCta = state?.key === 'resume_manual_only' && !isResumeLive;
  const showWorkflow = ['resume_requested', 'resume_dispatch_failed', 'resume_manual_only'].includes(state?.key || '');

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
              {task.mode} · {task.current_stage}
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
          {state.detail}
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

      {isExpanded && detail && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px dashed var(--border)', paddingTop: '10px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: '1.55' }}>
            {detail.summary?.display_state?.detail || state?.detail || '—'}
          </div>
          {candidate && (
            <div style={{ fontSize: '11px', color: 'var(--text-primary)', lineHeight: '1.55' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                {t('task_suggested_action')}
              </div>
              <div>{suggestedActionLabel(candidate)}</div>
              <div style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>{candidate.reason || '—'}</div>
            </div>
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
            <div style={{
              display: 'grid',
              gap: '8px',
              padding: '10px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: 'var(--bg-secondary)',
            }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                {t('task_workflow_title')}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
                <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_queued_by')}</div>
                <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{recovery.source || '—'}</div>
                <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_queued_at')}</div>
                <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(recovery.requested_at_ms || recovery.detected_at_ms)}</div>
                <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_workflow_next_step')}</div>
                <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{workflowNextStep(task)}</div>
              </div>
            </div>
          )}
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
              {t('task_outbox_title')}
            </div>
            {!detail.outboxEvents || detail.outboxEvents.length === 0 ? (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{t('task_outbox_empty')}</div>
            ) : detail.outboxEvents.map((event) => {
              const isOutboxOpen = expandedOutboxId === event.event_id;
              const eventTone = toneStyles(event.status === 'failed' ? 'error' : event.status === 'sent' ? 'success' : event.status === 'retrying' ? 'warning' : 'accent');
              const outboxBusy = busy === `outbox:${event.event_id}`;
              return (
                <div key={event.event_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-secondary)', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '11px', color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                        {event.effect_type}
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
                        {event.event_id}
                      </div>
                    </div>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      padding: '2px 8px',
                      borderRadius: '999px',
                      border: '1px solid',
                      fontSize: '10px',
                      fontFamily: 'var(--font-mono)',
                      ...eventTone,
                    }}>
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
                    {event.status === 'failed' && (
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
                  </div>
                  {isOutboxOpen && (
                    <div style={{ display: 'grid', gap: '8px' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: '6px 10px', fontSize: '11px', lineHeight: '1.55' }}>
                        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_target')}</div>
                        <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{event.target || '—'}</div>
                        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_attempts')}</div>
                        <div style={{ color: 'var(--text-primary)' }}>{event.attempts ?? 0}</div>
                        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_updated_at')}</div>
                        <div style={{ color: 'var(--text-primary)' }}>{formatEventTime(event.updated_at_ms)}</div>
                        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('task_outbox_error')}</div>
                        <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{event.error || '—'}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('task_outbox_payload')}</div>
                        <pre style={{ margin: 0, maxHeight: '180px', overflow: 'auto', padding: '8px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {JSON.stringify(event.payload || {}, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function TaskRecoveryPanel() {
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [expandedOutboxId, setExpandedOutboxId] = useState<string | null>(null);
  const timerRef = useRef<any>(null);

  useEffect(() => {
    loadTaskPanel(activeSessionKey.value);
  }, [activeSessionKey.value]);

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
        <div style={{ padding: '4px 10px', borderRadius: '999px', border: '1px solid rgba(255, 107, 53, 0.28)', background: 'rgba(255, 107, 53, 0.1)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent)' }}>
          {t('tasks_panel_manual_review_count')}: {recoverySummary.value?.manual_review_required || 0}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {sessionTasks.value.length === 0 ? (
          <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('tasks_panel_empty')}</div>
          </div>
        ) : (
          sessionTasks.value.map((task) => taskCard(task, expandedTaskId, setExpandedTaskId, expandedOutboxId, setExpandedOutboxId))
        )}

        {recoveryTasks.value.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.2px', marginTop: '4px' }}>
              {t('tasks_panel_manual_review')}
            </div>
            {recoveryTasks.value.slice(0, 4).map((task) => {
              const state = task.display_state;
              const tone = toneStyles(state?.tone || 'warning');
              return (
                <div key={`recovery-${task.task_id}`} style={{ padding: '10px 12px', borderRadius: '6px', border: '1px solid', background: tone.background, borderColor: tone.borderColor }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '11px', color: 'var(--text-primary)', marginBottom: '2px', wordBreak: 'break-word' }}>{task.goal || task.task_id}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{task.session_key}</div>
                    </div>
                    <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: tone.color }}>
                      {formatDisplayState(state)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
