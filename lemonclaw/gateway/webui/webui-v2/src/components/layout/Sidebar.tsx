import { useState } from 'preact/hooks';
import { SessionList } from '../sidebar/SessionList';
import { ActivityList } from '../sidebar/ActivityList';
import { activeSessionKey } from '../../stores/sessions';
import { SettingsModal } from '../settings/SettingsModal';
import { sidebarTab } from '../../stores/ui';
import { t, toggleLang, lang } from '../../stores/i18n';

export function Sidebar() {
  const [showSettings, setShowSettings] = useState(false);

  const handleNewChat = () => {
    sidebarTab.value = 'sessions';
    const newKey = 'webui:' + Math.random().toString(36).substring(2, 9);
    activeSessionKey.value = newKey;
  };

  return (
    <aside class="layout-sidebar">
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '16px', letterSpacing: '-0.5px' }}>
          Lemon<span style={{ color: 'var(--purple)', textShadow: '0 0 8px var(--purple-dim)' }}>Claw</span>
        </div>
      </div>

      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <button 
          onClick={() => sidebarTab.value = 'sessions'}
          style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'sessions' ? '2px solid var(--accent)' : '2px solid transparent', color: sidebarTab.value === 'sessions' ? 'var(--accent)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px', textTransform: 'uppercase', cursor: 'pointer', transition: 'all 0.2s' }}>
          {t('sessions')}
        </button>
        <button 
          onClick={() => sidebarTab.value = 'activity'}
          style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: sidebarTab.value === 'activity' ? '2px solid var(--teal)' : '2px solid transparent', color: sidebarTab.value === 'activity' ? 'var(--teal)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px', textTransform: 'uppercase', cursor: 'pointer', transition: 'all 0.2s' }}>
          {t('activity')}
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
        {sidebarTab.value === 'sessions' ? <SessionList /> : <ActivityList />}
      </div>

      <div style={{ padding: '16px', borderTop: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <button 
          onClick={handleNewChat}
          style={{ width: '100%', padding: '12px', background: 'transparent', border: '1px solid var(--accent)', borderRadius: '6px', color: 'var(--accent)', fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 'bold', cursor: 'pointer', textAlign: 'center', transition: 'all 0.2s', boxShadow: 'inset 0 0 8px rgba(255, 107, 53, 0.15)' }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255, 107, 53, 0.1)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          {t('new_chat')} MISSION
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button 
            onClick={toggleLang}
            style={{ width: '40px', padding: '8px 0', background: 'transparent', border: '1px solid transparent', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '12px', cursor: 'pointer', transition: 'all 0.2s' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
          >
            {lang.value === 'en' ? '中' : 'EN'}
          </button>
          <button 
            onClick={() => {
              const isLight = document.documentElement.getAttribute('data-theme') === 'light';
              if (isLight) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('lc_theme', 'dark');
              } else {
                document.documentElement.setAttribute('data-theme', 'light');
                localStorage.setItem('lc_theme', 'light');
              }
            }}
            style={{ width: '40px', padding: '8px 0', background: 'transparent', border: '1px solid transparent', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '12px', cursor: 'pointer', transition: 'all 0.2s' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
            title="Toggle Theme"
          >
            🌓
          </button>
          <button 
            onClick={() => setShowSettings(true)}
            style={{ flex: 1, padding: '8px', background: 'transparent', border: '1px solid transparent', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', display: 'flex', justifyContent: 'center', gap: '8px', transition: 'all 0.2s' }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-primary)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
          >
            <span style={{ color: 'var(--purple)' }}>⚙</span> {t('settings')}
          </button>
        </div>
      </div>
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </aside>
  );
}