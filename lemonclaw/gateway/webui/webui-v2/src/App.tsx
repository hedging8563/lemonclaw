import { useEffect, useState } from 'preact/hooks';
import { Sidebar } from './components/layout/Sidebar';
import { ChatArea } from './components/layout/ChatArea';
import { Inspector } from './components/layout/Inspector';
import { LoginScreen } from './components/auth/LoginScreen';
import { SettingsModal } from './components/settings/SettingsModal';
import { closeSessionStream, syncSessionStream } from './stores/chat';
import { activeSessionKey } from './stores/sessions';
import { checkAuth, isAuthenticated, authRequired } from './stores/auth';
import { initActivityWS } from './stores/activity';
import { CommandPalette } from './components/layout/CommandPalette';
import { mobileMenuOpen, showSettings } from './stores/ui';
import { t } from './stores/i18n';

export function App() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuth().then((data) => {
      setLoading(false);
      if (data.ok) initActivityWS();
    });
    return () => closeSessionStream();
  }, []);

  useEffect(() => {
    if (!loading && isAuthenticated.value) {
      syncSessionStream();
    }
  }, [loading, isAuthenticated.value, activeSessionKey.value]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', background: 'radial-gradient(circle at top, rgba(255, 107, 53, 0.08), transparent 34%), var(--bg-primary)', padding: '24px' }}>
        <div style={{ width: '100%', maxWidth: '460px', background: 'linear-gradient(180deg, rgba(255,255,255,0.04) 0%, var(--bg-secondary) 18%)', border: '1px solid var(--border)', borderRadius: '20px', padding: '24px', boxShadow: '0 22px 48px rgba(0,0,0,0.24)' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 10px', borderRadius: '999px', border: '1px solid var(--border)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '14px' }}>
            <span>Opening</span>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent)' }} />
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '18px', color: 'var(--text-primary)', marginBottom: '10px', lineHeight: 1.35 }}>
            {t('loading_app_title')}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            {t('loading_app_desc')}
          </div>
        </div>
      </div>
    );
  }

  if (authRequired.value && !isAuthenticated.value) {
    return <LoginScreen />;
  }

  return (
    <div class="app-container">
      {mobileMenuOpen.value && <div class="mobile-overlay" onClick={() => mobileMenuOpen.value = false}></div>}
      <CommandPalette />
      <Sidebar />
      <ChatArea />
      <Inspector />
      {showSettings.value && <SettingsModal onClose={() => showSettings.value = false} />}
    </div>
  );
}
