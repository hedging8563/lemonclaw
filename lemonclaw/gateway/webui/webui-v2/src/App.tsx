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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', background: 'radial-gradient(circle at top, rgba(124, 58, 237, 0.08), transparent 34%), var(--bg-primary)', padding: '24px' }}>
        <div style={{ width: '100%', maxWidth: '460px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '24px', padding: '32px', boxShadow: '0 24px 64px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.02)' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 12px', borderRadius: '999px', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '20px' }}>
            <span>Initializing</span>
            <span class="pulse-dot" />
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: '24px', color: 'var(--text-primary)', marginBottom: '12px', lineHeight: 1.35, fontWeight: '600', letterSpacing: '-0.02em' }}>
            {t('loading_app_title')}
          </div>
          <div style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
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
