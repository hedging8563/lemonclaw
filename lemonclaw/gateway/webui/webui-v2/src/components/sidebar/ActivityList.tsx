import { useEffect } from 'preact/hooks';
import { activitySessions, loadActivitySessions } from '../../stores/activity';
import { activeSessionKey } from '../../stores/sessions'; 
import { t } from '../../stores/i18n';

export function ActivityList() {
  useEffect(() => {
    loadActivitySessions();
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '12px 8px' }}>
      {activitySessions.value.length === 0 && (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>{t('no_activity')}</div>
      )}
      {activitySessions.value.map(session => (
        <div 
          key={session.key}
          onClick={() => activeSessionKey.value = session.key}
          style={{
            display: 'flex', alignItems: 'flex-start', padding: '8px 12px', borderRadius: '6px', cursor: 'pointer', gap: '8px', marginBottom: '2px',
            background: activeSessionKey.value === session.key ? 'var(--bg-tertiary)' : 'transparent',
            border: '1px solid', borderColor: activeSessionKey.value === session.key ? 'var(--border)' : 'transparent',
            transition: 'all 0.15s'
          }}
          onMouseEnter={(e) => { if(activeSessionKey.value !== session.key) e.currentTarget.style.background = 'var(--bg-hover)' }}
          onMouseLeave={(e) => { if(activeSessionKey.value !== session.key) e.currentTarget.style.background = 'transparent' }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
             <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', padding: '1px 6px', border: '1px solid var(--border)', borderRadius: '3px', color: 'var(--teal)' }}>{session.channel}</span>
                <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', fontFamily: 'var(--font-mono)', color: activeSessionKey.value === session.key ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                  {session.title || session.key}
                </span>
             </div>
             <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
                {new Date(session.updated_at).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}
             </div>
          </div>
        </div>
      ))}
    </div>
  );
}