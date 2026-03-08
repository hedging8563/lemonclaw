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
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('loading')}</div>;
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