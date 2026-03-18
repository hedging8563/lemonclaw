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
  const [hovered, setHovered] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth < 768);
      }
    };
    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
  }, []);

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

  const formatRelativeTime = (value: string) => {
    const stamp = new Date(value).getTime();
    if (!stamp) return '—';
    const diff = Date.now() - stamp;
    const minute = 60 * 1000;
    const hour = 60 * minute;
    if (diff < minute) return t('time_just_now');
    if (diff < hour) return t('time_minutes_ago').replace('{n}', String(Math.max(1, Math.round(diff / minute))));
    if (diff < 24 * hour) return t('time_hours_ago').replace('{n}', String(Math.max(1, Math.round(diff / hour))));
    return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div 
      onClick={() => { if(!isEditing) { activeSessionKey.value = session.key; mobileMenuOpen.value = false; } }}
      onDblClick={() => setIsEditing(true)}
      onMouseEnter={(e) => {
        setHovered(true);
        if (!isActive) e.currentTarget.style.background = 'var(--bg-hover)';
      }}
      onMouseLeave={(e) => {
        setHovered(false);
        if (!isActive) e.currentTarget.style.background = 'transparent';
      }}
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
            {session.title || t('unnamed_chat')}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>
          <span style={{ color: isActive ? 'var(--teal)' : 'var(--border)', fontSize: '8px' }}>●</span>
          {formatRelativeTime(session.updated_at)}
          <span>· {session.message_count} {t('session_messages')}</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', opacity: hovered || isActive || isEditing || isMobile ? 1 : 0.18, transition: 'opacity 0.15s', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {!isEditing && (
          <button
            onClick={(e) => { e.stopPropagation(); setTitle(session.title || ''); setIsEditing(true); }}
            style={{ background: 'none', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px', fontFamily: 'var(--font-mono)', borderRadius: '999px', padding: '2px 6px' }}
            title={t('rename_session')}
          >
            {t('rename_session')}
          </button>
        )}
        <button 
          onClick={(e) => { e.stopPropagation(); if(confirm(t('confirm_delete_session'))) deleteSession(session.key); }}
          style={{ background: 'none', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px', fontFamily: 'var(--font-mono)', borderRadius: '999px', padding: '2px 6px' }}
          title={t('delete_session')}
          onMouseEnter={(e) => e.currentTarget.style.color = 'var(--error)'}
          onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-muted)'}
        >
          {t('delete_session')}
        </button>
      </div>
    </div>
  );
}
