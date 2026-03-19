import { useEffect } from 'preact/hooks';
import { sessions, loadSessions } from '../../stores/sessions';
import { t } from '../../stores/i18n';
import { SessionItem } from './SessionItem';

export function SessionList() {
  useEffect(() => {
    loadSessions();
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
      {sessions.value.length === 0 && (
        <div style={{ margin: '12px 6px', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg-secondary)' }}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--text-primary)', marginBottom: '6px' }}>
            {t('session_empty_title')}
          </div>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
            {t('session_empty_desc')}
          </div>
        </div>
      )}
      {sessions.value.map(session => (
        <SessionItem key={session.key} session={session} />
      ))}
    </div>
  );
}
