import { useEffect, useRef, useState } from 'preact/hooks';
import { activitySessions } from '../../stores/activity';
import { t } from '../../stores/i18n';
import { activeSessionKey, sessions } from '../../stores/sessions';

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
      setQuery('');
      setSelectedIndex(0);
    }
  }, [open]);

  if (!open) return null;

  const allItems = [
    ...sessions.value.map((session) => ({ ...session, type: 'webui' })),
    ...activitySessions.value.map((session) => ({ ...session, type: 'activity' })),
  ];

  const filtered = allItems.filter((item) =>
    (item.title || item.key).toLowerCase().includes(query.toLowerCase()) ||
    item.key.toLowerCase().includes(query.toLowerCase())
  );

  const handleSelect = (key: string) => {
    activeSessionKey.value = key;
    setOpen(false);
  };

  const handleListKeyDown = (e: KeyboardEvent) => {
    if (!filtered.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((index) => {
        const next = (index + 1) % filtered.length;
        document.getElementById(`cmd-item-${next}`)?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((index) => {
        const next = (index - 1 + filtered.length) % filtered.length;
        document.getElementById(`cmd-item-${next}`)?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'Enter' && filtered[selectedIndex]) {
      e.preventDefault();
      handleSelect(filtered[selectedIndex].key);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 10000, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: 'max(12px, env(safe-area-inset-top)) 12px 12px', backdropFilter: 'blur(2px)' }} onClick={() => setOpen(false)}>
      <div style={{ width: 'min(600px, calc(100vw - 24px))', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', maxHeight: 'min(70dvh, calc(100dvh - 24px))', animation: 'slideUpFade 0.2s ease-out' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '18px', opacity: 0.5 }}>🔍</span>
          <input
            ref={inputRef}
            value={query}
            onInput={(e) => { setQuery((e.target as HTMLInputElement).value); setSelectedIndex(0); }}
            onKeyDown={handleListKeyDown}
            placeholder={t('cmd_search_placeholder')}
            style={{ flex: 1, minWidth: 0, background: 'transparent', border: 'none', color: 'var(--text-primary)', outline: 'none', fontSize: '16px', fontFamily: 'var(--font-mono)' }}
          />
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', border: '1px solid var(--border)', padding: '2px 6px', borderRadius: '4px', flexShrink: 0 }}>ESC</span>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {filtered.length === 0 && <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('cmd_no_results')}</div>}
          {filtered.map((item, idx) => (
            <div
              key={item.key}
              id={`cmd-item-${idx}`}
              onClick={() => handleSelect(item.key)}
              onMouseEnter={() => setSelectedIndex(idx)}
              style={{ padding: '12px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', background: selectedIndex === idx ? 'var(--bg-tertiary)' : 'transparent', borderLeft: selectedIndex === idx ? '3px solid var(--accent)' : '3px solid transparent' }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0, flex: 1 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: selectedIndex === idx ? 'var(--text-primary)' : 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.title || item.key}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.key}
                </div>
              </div>
              <div style={{ fontSize: '10px', color: item.type === 'webui' ? 'var(--accent)' : 'var(--teal)', border: '1px solid', padding: '2px 6px', borderRadius: '4px', textTransform: 'uppercase', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                {item.type}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
