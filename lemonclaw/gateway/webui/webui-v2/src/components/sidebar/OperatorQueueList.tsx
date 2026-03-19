import { useEffect, useRef } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { activeOperatorTaskId, loadOperatorQueue, operatorQueueTasks, recoverySummary } from '../../stores/tasks';
import { t } from '../../stores/i18n';
import { mobileMenuOpen, showInspector } from '../../stores/ui';

function humanizeCode(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  return raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function formatQueueAction(action?: string | null, fallbackStage?: string | null) {
  const key = String(action || fallbackStage || '').trim();
  if (!key) return '—';
  const actionLabel = t(`task_action_${key}` as any);
  if (actionLabel !== `task_action_${key}`) return actionLabel;
  const stateLabel = t(`task_state_${key}` as any);
  if (stateLabel !== `task_state_${key}`) return stateLabel;
  return humanizeCode(key);
}

function formatQueueSource(source?: string | null) {
  const raw = String(source || '').trim();
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

export function OperatorQueueList() {
  const timerRef = useRef<any>(null);

  useEffect(() => {
    loadOperatorQueue();
  }, []);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadOperatorQueue();
      }
    }, 15000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '12px 8px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px', padding: '0 4px' }}>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)', fontFamily: 'var(--font-ui)', fontSize: '12px', color: 'var(--text-secondary)' }}>
          {t('tasks_panel_manual_review_count')}: {recoverySummary.value?.manual_review_required || 0}
        </div>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid rgba(255, 107, 53, 0.28)', background: 'rgba(255, 107, 53, 0.1)', fontFamily: 'var(--font-ui)', fontSize: '12px', color: 'var(--accent)' }}>
          {t('operator_queue_count')}: {operatorQueueTasks.value.length}
        </div>
      </div>

      {operatorQueueTasks.value.length === 0 && (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', fontFamily: 'var(--font-ui)' }}>
          {t('operator_queue_empty')}
        </div>
      )}

      {operatorQueueTasks.value.map((task) => {
        const active = activeOperatorTaskId.value === task.task_id;
        const queue = task.queue || {};
        return (
          <div
            key={task.task_id}
            onClick={() => {
              activeOperatorTaskId.value = task.task_id;
              activeSessionKey.value = task.session_key;
              showInspector.value = true;
              mobileMenuOpen.value = false;
            }}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              padding: '10px 12px',
              borderRadius: '6px',
              cursor: 'pointer',
              gap: '8px',
              marginBottom: '6px',
              background: active ? 'var(--bg-tertiary)' : 'transparent',
              border: '1px solid',
              borderColor: active ? 'var(--accent)' : 'transparent',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'var(--bg-hover)'; }}
            onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: '9px', padding: '1px 6px', border: '1px solid var(--border)', borderRadius: '3px', color: 'var(--accent)' }}>
                  {formatQueueAction(queue.recommended_action, task.current_stage)}
                </span>
                <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', fontFamily: 'var(--font-display)', color: active ? 'var(--text-primary)' : 'var(--text-secondary)', letterSpacing: '-0.01em' }}>
                  {task.goal || task.task_id}
                </span>
              </div>
              <div style={{ fontFamily: 'var(--font-ui)', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', wordBreak: 'break-word' }}>
                {`${t('label_source')}: ${formatQueueSource(queue.source)}`}
              </div>
              <div style={{ fontFamily: 'var(--font-ui)', fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                {`${t('label_reason')}: ${queue.reason || '—'}`}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
