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

  const actionsVisible = isActive || isEditing || isMobile || hovered;

  return (
    <div 
      onClick={() => { if(!isEditing) { activeSessionKey.value = session.key; mobileMenuOpen.value = false; } }}
      onDblClick={() => setIsEditing(true)}
      onMouseEnter={(e) => {
        if (!isMobile) {
          setHovered(true);
          if (!isActive) e.currentTarget.style.background = 'var(--bg-hover)';
        }
      }}
      onMouseLeave={(e) => {
        if (!isMobile) {
          setHovered(false);
          if (!isActive) e.currentTarget.style.background = 'transparent';
        }
      }}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        minHeight: isMobile ? '56px' : '48px',
        padding: isMobile ? '10px 10px' : '8px 12px',
        borderRadius: '6px',
        cursor: 'pointer',
        gap: isMobile ? '10px' : '8px',
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
            style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--accent)', color: 'var(--text-primary)', padding: isMobile ? '4px 6px' : '2px 4px', borderRadius: '4px', fontSize: isMobile ? '14px' : '12px', fontFamily: 'var(--font-ui)', outline: 'none' }}
          />
        ) : (
          <div style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '15px', lineHeight: '1.3', fontFamily: 'var(--font-ui)', color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
            {session.title || t('unnamed_chat')}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: isMobile ? '5px' : '3px', fontFamily: 'var(--font-ui)', fontSize: isMobile ? '11px' : '10px', color: 'var(--text-muted)', flexWrap: 'nowrap', overflow: 'hidden', minWidth: 0 }}>
          <span style={{ color: isActive ? 'var(--teal)' : 'var(--border)', fontSize: '8px' }}>●</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{formatRelativeTime(session.updated_at)}</span>
          <span style={{ whiteSpace: 'nowrap' }}>· {session.message_count} {t('session_messages')}</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '6px' : '4px', opacity: actionsVisible ? 1 : 0.18, transition: 'opacity 0.15s', justifyContent: 'flex-end' }}>
        {!isEditing && (
          <button
            onClick={(e) => { e.stopPropagation(); setTitle(session.title || ''); setIsEditing(true); }}
            style={{ background: 'none', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: isMobile ? '11px' : '10px', fontFamily: 'var(--font-ui)', borderRadius: '999px', padding: isMobile ? '6px 10px' : '2px 6px', minHeight: isMobile ? '32px' : 'auto', touchAction: 'manipulation', whiteSpace: 'nowrap' }}
            title={t('rename_session')}
          >
            {t('rename_session')}
          </button>
        )}
        <button 
          onClick={(e) => { e.stopPropagation(); if(confirm(t('confirm_delete_session'))) deleteSession(session.key); }}
          style={{ background: 'none', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: isMobile ? '11px' : '10px', fontFamily: 'var(--font-ui)', borderRadius: '999px', padding: isMobile ? '6px 10px' : '2px 6px', minHeight: isMobile ? '32px' : 'auto', touchAction: 'manipulation', whiteSpace: 'nowrap' }}
          title={t('delete_session')}
          onMouseEnter={(e) => { if (!isMobile) e.currentTarget.style.color = 'var(--error)'; }}
          onMouseLeave={(e) => { if (!isMobile) e.currentTarget.style.color = 'var(--text-muted)'; }}
        >
          {t('delete_session')}
        </button>
      </div>
    </div>
  );
}
