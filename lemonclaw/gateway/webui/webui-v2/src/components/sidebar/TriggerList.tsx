import { useEffect, useRef } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { activeOperatorTaskId } from '../../stores/tasks';
import { t } from '../../stores/i18n';
import { mobileMenuOpen, showInspector, sidebarTab } from '../../stores/ui';
import { loadTriggers, selectedTriggerFamily, triggerPanelError, triggerSummary, triggers } from '../../stores/triggers';

function humanizeCode(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  return raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function formatTriggerFamily(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return 'runtime';
  const mapped: Record<string, string> = {
    runtime: 'runtime',
    channel: 'channel',
    cron: 'scheduled',
    webhook: 'webhook',
    manual: 'manual',
  };
  return humanizeCode(mapped[raw] || raw);
}

function formatTriggerSource(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return 'trigger';
  const mapped: Record<string, string> = {
    cron: 'scheduled run',
    webhook: 'webhook',
    runtime: 'runtime',
    chat: 'chat',
    channel: 'channel',
  };
  return humanizeCode(mapped[raw] || raw);
}

function formatTriggerStatus(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return 'unknown';
  const mapped: Record<string, string> = {
    received: 'received',
    dispatching: 'sending',
    dispatched: 'sent',
    ok: 'done',
    error: 'failed',
    skipped: 'skipped',
  };
  return humanizeCode(mapped[raw] || raw);
}

function formatTriggerTime(value?: number): string {
  const stamp = Number(value || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

export function TriggerList() {
  const timerRef = useRef<any>(null);
  const families = Object.keys(triggerSummary.value?.by_family || {}).sort();

  useEffect(() => {
    loadTriggers();
  }, []);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadTriggers();
      }
    }, 15000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '12px 8px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px', padding: '0 4px' }}>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)', fontFamily: 'var(--font-ui)', fontSize: '13px', color: 'var(--text-secondary)' }}>
          {t('trigger_count')}: {triggers.value.length}
        </div>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid rgba(10, 186, 181, 0.24)', background: 'rgba(10, 186, 181, 0.08)', fontFamily: 'var(--font-ui)', fontSize: '13px', color: 'var(--teal)' }}>
          {t('trigger_source_count')}: {Object.keys(triggerSummary.value?.by_source || {}).length}
        </div>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid rgba(124, 58, 237, 0.2)', background: 'rgba(124, 58, 237, 0.08)', fontFamily: 'var(--font-ui)', fontSize: '13px', color: 'var(--accent)' }}>
          {t('trigger_family_count')}: {families.length}
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px', padding: '0 4px' }}>
        {[{ key: '', label: t('trigger_family_all') }, ...families.map((family) => ({ key: family, label: formatTriggerFamily(family) }))].map((item) => {
          const active = selectedTriggerFamily.value === item.key;
          return (
            <button
              key={item.key || 'all'}
              onClick={() => void loadTriggers(item.key)}
              style={{
                appearance: 'none',
                border: '1px solid',
                borderColor: active ? 'var(--accent)' : 'var(--border)',
                background: active ? 'rgba(124, 58, 237, 0.12)' : 'var(--bg-primary)',
                color: active ? 'var(--accent)' : 'var(--text-secondary)',
                borderRadius: '999px',
                padding: '4px 8px',
                fontFamily: 'var(--font-ui)',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      {triggerPanelError.value && (
        <div style={{ padding: '12px', color: 'var(--error)', fontFamily: 'var(--font-ui)', fontSize: '13px' }}>
          {triggerPanelError.value}
        </div>
      )}

      {triggers.value.length === 0 && !triggerPanelError.value && (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px', fontFamily: 'var(--font-ui)' }}>
          {t('trigger_empty')}
        </div>
      )}

      {triggers.value.map((item) => {
        const active = item.session_key && activeSessionKey.value === item.session_key;
        return (
          <div
            key={item.trigger_id}
            onClick={() => {
              if (item.session_key) activeSessionKey.value = item.session_key;
              if (item.task_id) {
                activeOperatorTaskId.value = item.task_id;
                showInspector.value = true;
              }
              sidebarTab.value = 'sessions';
              mobileMenuOpen.value = false;
            }}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              padding: '10px 12px',
              borderRadius: '6px',
              cursor: item.session_key ? 'pointer' : 'default',
              gap: '8px',
              marginBottom: '6px',
              background: active ? 'var(--bg-tertiary)' : 'transparent',
              border: '1px solid',
              borderColor: active ? 'var(--accent)' : 'transparent',
              transition: 'all 0.15s',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: '9px', padding: '1px 6px', border: '1px solid rgba(124, 58, 237, 0.18)', borderRadius: '3px', color: 'var(--accent)', background: 'rgba(124, 58, 237, 0.08)' }}>
                  {formatTriggerFamily(item.family)}
                </span>
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: '9px', padding: '1px 6px', border: '1px solid var(--border)', borderRadius: '3px', color: 'var(--accent)' }}>
                  {formatTriggerSource(item.source)}
                </span>
                <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '13px', fontFamily: 'var(--font-display)', color: active ? 'var(--text-primary)' : 'var(--text-secondary)', letterSpacing: '-0.01em' }}>
                  {item.kind || item.trigger_id}
                </span>
              </div>
              <div style={{ fontFamily: 'var(--font-ui)', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', wordBreak: 'break-word' }}>
                {item.payload_summary || item.session_key || '—'}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontFamily: 'var(--font-ui)', fontSize: '12px', color: 'var(--text-muted)' }}>
                <span>{`${t('label_status')}: ${formatTriggerStatus(item.status)}`}</span>
                <span>{formatTriggerTime(item.updated_at_ms)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
