import { useEffect, useRef } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { t } from '../../stores/i18n';
import { mobileMenuOpen, sidebarTab } from '../../stores/ui';
import { loadTriggers, triggerPanelError, triggerSummary, triggers } from '../../stores/triggers';

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
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-secondary)' }}>
          {t('trigger_count')}: {triggers.value.length}
        </div>
        <div style={{ padding: '4px 8px', borderRadius: '999px', border: '1px solid rgba(10, 186, 181, 0.24)', background: 'rgba(10, 186, 181, 0.08)', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--teal)' }}>
          {t('trigger_source_count')}: {Object.keys(triggerSummary.value?.by_source || {}).length}
        </div>
      </div>

      {triggerPanelError.value && (
        <div style={{ padding: '12px', color: 'var(--error)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
          {triggerPanelError.value}
        </div>
      )}

      {triggers.value.length === 0 && !triggerPanelError.value && (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
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
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', padding: '1px 6px', border: '1px solid var(--border)', borderRadius: '3px', color: 'var(--accent)' }}>
                  {item.source || 'trigger'}
                </span>
                <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', fontFamily: 'var(--font-mono)', color: active ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                  {item.kind || item.trigger_id}
                </span>
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', wordBreak: 'break-word' }}>
                {item.payload_summary || item.session_key || '—'}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
                <span>{item.status || 'unknown'}</span>
                <span>{formatTriggerTime(item.updated_at_ms)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
