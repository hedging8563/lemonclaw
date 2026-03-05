import { Session, activeSessionKey, deleteSession } from '../../stores/sessions';
import { t } from '../../stores/i18n';

export function SessionItem({ session }: { session: Session }) {
  const isActive = activeSessionKey.value === session.key;
  
  return (
    <div 
      onClick={() => activeSessionKey.value = session.key}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        padding: '8px 12px',
        borderRadius: '6px',
        cursor: 'pointer',
        gap: '8px',
        marginBottom: '2px',
        background: isActive ? 'var(--bg-tertiary)' : 'transparent',
        border: '1px solid',
        borderColor: isActive ? 'var(--border)' : 'transparent',
        transition: 'all 0.15s'
      }}
      onMouseEnter={(e) => { if(!isActive) e.currentTarget.style.background = 'var(--bg-hover)' }}
      onMouseLeave={(e) => { if(!isActive) e.currentTarget.style.background = 'transparent' }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', lineHeight: '1.3', fontFamily: 'var(--font-mono)', color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
          {session.title || t('new_chat_fallback')}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
          <span style={{ color: isActive ? 'var(--teal)' : 'var(--border)', fontSize: '8px' }}>●</span>
          {new Date(session.updated_at).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}
          <span>· {session.message_count} msg</span>
        </div>
      </div>
      <button 
        onClick={(e) => { e.stopPropagation(); if(confirm('Delete this session permanently?')) deleteSession(session.key); }}
        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', fontFamily: 'var(--font-mono)' }}
        title="Delete Session"
        onMouseEnter={(e) => e.currentTarget.style.color = 'var(--error)'}
        onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-muted)'}
      >
        ×
      </button>
    </div>
  );
}