import { useEffect, useState } from 'preact/hooks';
import { t, toggleLang, lang } from '../../stores/i18n';
import { activeSessionKey } from '../../stores/sessions';
import { mobileMenuOpen, sidebarTab, showSettings } from '../../stores/ui';
import { ActivityList } from '../sidebar/ActivityList';
import { OperatorQueueList } from '../sidebar/OperatorQueueList';
import { SessionList } from '../sidebar/SessionList';
import { TriggerList } from '../sidebar/TriggerList';

export function Sidebar() {
  const [isMobile, setIsMobile] = useState(false);
  const [themeMode, setThemeMode] = useState<'light' | 'dark'>(() => {
    if (typeof document === 'undefined') return 'dark';
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  });

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

  useEffect(() => {
    if (typeof document === 'undefined') return;
    setThemeMode(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
  }, []);

  const handleNewChat = () => {
    sidebarTab.value = 'sessions';
    const newKey = `webui:${Math.random().toString(36).substring(2, 9)}`;
    activeSessionKey.value = newKey;
    mobileMenuOpen.value = false;
  };

  const toggleTheme = () => {
    const nextMode = themeMode === 'light' ? 'dark' : 'light';
    if (nextMode === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      localStorage.setItem('lc_theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('lc_theme', 'dark');
    }
    setThemeMode(nextMode);
  };

  return (
    <aside class={`layout-sidebar ${mobileMenuOpen.value ? 'open' : ''}`}>
      <div style={{ padding: isMobile ? '12px' : '0 16px', height: '56px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <img src="/logo-icon.svg" alt="" style={{ width: '22px', height: '22px', flexShrink: 0 }} />
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: isMobile ? '16px' : '18px', letterSpacing: '-0.5px', minWidth: 0, color: 'var(--text-primary)' }}>
            Lemon<span style={{ color: 'var(--purple)', textShadow: '0 0 8px var(--purple-dim)' }}>Claw</span>
          </div>
        </div>
        <button class="sidebar-mobile-close" onClick={() => { mobileMenuOpen.value = false; }} style={{ display: isMobile ? 'flex' : 'none', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: '22px', cursor: 'pointer', lineHeight: 1, width: '38px', height: '38px', borderRadius: '10px', touchAction: 'manipulation' }}>
          ×
        </button>
      </div>

      <div style={{ display: isMobile ? 'grid' : 'flex', gridTemplateColumns: isMobile ? 'repeat(2, minmax(0, 1fr))' : undefined, borderBottom: '1px solid var(--border)', flexShrink: 0, overflowX: 'auto', scrollbarWidth: 'none' }}>
        <button onClick={() => sidebarTab.value = 'sessions'} style={{ flex: 1, minHeight: isMobile ? '46px' : '40px', padding: isMobile ? '0 10px' : '0 4px', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'sessions' ? '2px solid var(--accent)' : '2px solid transparent', color: sidebarTab.value === 'sessions' ? 'var(--accent)' : 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '13px', textTransform: 'none', cursor: 'pointer', transition: 'all 0.2s', letterSpacing: '0.2px', touchAction: 'manipulation', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {t('sessions')}
        </button>
        <button onClick={() => sidebarTab.value = 'activity'} style={{ flex: 1, minHeight: isMobile ? '46px' : '40px', padding: isMobile ? '0 10px' : '0 4px', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'activity' ? '2px solid var(--teal)' : '2px solid transparent', color: sidebarTab.value === 'activity' ? 'var(--teal)' : 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '13px', textTransform: 'none', cursor: 'pointer', transition: 'all 0.2s', letterSpacing: '0.2px', touchAction: 'manipulation', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {t('activity')}
        </button>
        <button onClick={() => sidebarTab.value = 'operatorQueue'} style={{ flex: 1, minHeight: isMobile ? '46px' : '40px', padding: isMobile ? '0 10px' : '0 4px', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'operatorQueue' ? '2px solid var(--accent)' : '2px solid transparent', color: sidebarTab.value === 'operatorQueue' ? 'var(--accent)' : 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '13px', textTransform: 'none', cursor: 'pointer', transition: 'all 0.2s', letterSpacing: '0.2px', touchAction: 'manipulation', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {t('operator_queue')}
        </button>
        <button onClick={() => sidebarTab.value = 'triggers'} style={{ flex: 1, minHeight: isMobile ? '46px' : '40px', padding: isMobile ? '0 10px' : '0 4px', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'triggers' ? '2px solid var(--teal)' : '2px solid transparent', color: sidebarTab.value === 'triggers' ? 'var(--teal)' : 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '13px', textTransform: 'none', cursor: 'pointer', transition: 'all 0.2s', letterSpacing: '0.2px', touchAction: 'manipulation', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>
          {t('triggers')}
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
        {sidebarTab.value === 'sessions'
          ? <SessionList />
          : sidebarTab.value === 'activity'
            ? <ActivityList />
            : sidebarTab.value === 'operatorQueue'
              ? <OperatorQueueList />
              : <TriggerList />}
      </div>

      <div style={{ padding: isMobile ? '10px 12px' : '16px', borderTop: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', gap: isMobile ? '10px' : '8px' }}>
        <button
          onClick={handleNewChat}
          style={{ width: '100%', minHeight: isMobile ? '44px' : '40px', padding: isMobile ? '0 12px' : '12px', background: 'transparent', border: '1px solid var(--accent)', borderRadius: '6px', color: 'var(--accent)', fontFamily: 'var(--font-ui)', fontSize: isMobile ? '13px' : '14px', fontWeight: 'bold', cursor: 'pointer', textAlign: 'center', transition: 'all 0.2s', boxShadow: 'inset 0 0 8px rgba(255, 107, 53, 0.15)', touchAction: 'manipulation' }}
          onMouseEnter={(e) => { if (!isMobile) { e.currentTarget.style.background = 'rgba(255, 107, 53, 0.1)'; } }}
          onMouseLeave={(e) => { if (!isMobile) { e.currentTarget.style.background = 'transparent'; } }}
        >
          {t('new_chat_button')}
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={toggleLang} style={{ width: '40px', minHeight: isMobile ? '40px' : '32px', padding: isMobile ? '0' : '8px 0', background: 'transparent', border: '1px solid transparent', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: 'pointer', transition: 'all 0.2s', touchAction: 'manipulation' }} onMouseEnter={(e) => { if (!isMobile) { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; } }} onMouseLeave={(e) => { if (!isMobile) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; } }}>
            {lang.value === 'en' ? '中' : 'EN'}
          </button>
          <button onClick={toggleTheme} style={{ width: '40px', minHeight: isMobile ? '40px' : '32px', padding: 0, background: 'transparent', border: '1px solid transparent', borderRadius: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: 'pointer', transition: 'all 0.2s', touchAction: 'manipulation', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onMouseEnter={(e) => { if (!isMobile) { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; } }} onMouseLeave={(e) => { if (!isMobile) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; } }} title={t('toggle_theme')}>
            <span
              aria-hidden="true"
              style={{
                position: 'relative',
                width: isMobile ? '24px' : '22px',
                height: isMobile ? '24px' : '22px',
                borderRadius: '999px',
                background: themeMode === 'light'
                  ? 'linear-gradient(135deg, #0f172a 0%, #1e293b 48%, #f7d76a 49%, #fde68a 100%)'
                  : 'linear-gradient(135deg, #f8fafc 0%, #dbeafe 42%, #7c3aed 43%, #312e81 100%)',
                boxShadow: themeMode === 'light'
                  ? '0 0 0 1px rgba(15, 23, 42, 0.08), 0 6px 14px rgba(15, 23, 42, 0.18)'
                  : '0 0 0 1px rgba(124, 58, 237, 0.16), 0 6px 14px rgba(76, 29, 149, 0.24)',
                overflow: 'hidden',
                display: 'inline-block',
              }}
            >
              <span
                style={{
                  position: 'absolute',
                  inset: themeMode === 'light' ? '2px auto auto 3px' : '2px 3px auto auto',
                  width: '8px',
                  height: '8px',
                  borderRadius: '999px',
                  background: themeMode === 'light' ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.72)',
                  boxShadow: themeMode === 'light' ? '0 0 0 1px rgba(255,255,255,0.12)' : '0 0 0 1px rgba(255,255,255,0.28)',
                }}
              />
            </span>
          </button>
          <button onClick={() => showSettings.value = true} style={{ flex: 1, minWidth: 0, minHeight: isMobile ? '40px' : '32px', padding: isMobile ? '0 8px' : '8px', background: 'transparent', border: '1px solid transparent', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-display)', fontSize: '14px', cursor: 'pointer', display: 'flex', justifyContent: 'center', gap: isMobile ? '6px' : '8px', alignItems: 'center', transition: 'all 0.2s', touchAction: 'manipulation', fontWeight: 500 }} onMouseEnter={(e) => { if (!isMobile) { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; } }} onMouseLeave={(e) => { if (!isMobile) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; } }}>
            <span style={{ color: 'var(--purple)' }}>⚙</span> <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('settings')}</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
