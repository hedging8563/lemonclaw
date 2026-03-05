import { useState, useRef, useEffect } from 'preact/hooks';
import { activeSessionKey, deleteSession, loadSessions } from '../../stores/sessions';
import type { Session } from '../../stores/sessions';
import { t } from '../../stores/i18n';
import { apiFetch } from '../../api/client';
import { mobileMenuOpen } from '../../stores/ui';

export function SessionItem({ session }: { session: Session }) {
  const isActive = activeSessionKey.value === session.key;
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  const handleRename = async () => {
    if (!title.trim() || title === session.title) {
      setIsEditing(false);
      return;
    }
    try {
      await apiFetch(`/api/sessions/${session.key}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: title.trim() })
      });
      await loadSessions();
    } catch (e) {
      console.error('Rename failed', e);
    }
    setIsEditing(false);
  };

  return (
    <div 
      onClick={() => { if(!isEditing) { activeSessionKey.value = session.key; mobileMenuOpen.value = false; } }}
      onDblClick={() => setIsEditing(true)}
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
        {isEditing ? (
          <input 
            ref={inputRef}
            value={title}
            onInput={e => setTitle((e.target as HTMLInputElement).value)}
            onKeyDown={e => { if(e.key === 'Enter') handleRename(); if(e.key === 'Escape') setIsEditing(false); }}
            onBlur={handleRename}
            style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--accent)', color: 'var(--text-primary)', padding: '2px 4px', borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--font-mono)', outline: 'none' }}
          />
        ) : (
          <div style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', lineHeight: '1.3', fontFamily: 'var(--font-mono)', color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
            {session.title || t('new_chat_fallback')}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
          <span style={{ color: isActive ? 'var(--teal)' : 'var(--border)', fontSize: '8px' }}>●</span>
          {new Date(session.updated_at).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}
          <span>· {session.message_count} msg</span>
        </div>
      </div>
      <button 
        onClick={(e) => { e.stopPropagation(); if(confirm(t('confirm_delete_session'))) deleteSession(session.key); }}
        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', fontFamily: 'var(--font-mono)' }}
        title={t('delete_session')}
        onMouseEnter={(e) => e.currentTarget.style.color = 'var(--error)'}
        onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-muted)'}
      >
        ×
      </button>
    </div>
  );
}