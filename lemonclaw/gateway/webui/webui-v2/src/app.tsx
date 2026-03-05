import { useEffect, useState } from 'preact/hooks';
import { Sidebar } from './components/layout/Sidebar';
import { ChatArea } from './components/layout/ChatArea';
import { Inspector } from './components/layout/Inspector';
import { LoginScreen } from './components/auth/LoginScreen';
import { checkAuth, isAuthenticated, authRequired } from './stores/auth';
import { initActivityWS } from './stores/activity';
import { CommandPalette } from './components/layout/CommandPalette';
import { mobileMenuOpen } from './stores/ui';

export function App() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuth().then((data) => {
      setLoading(false);
      if (data.ok) initActivityWS();
    });
  }, []);

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>Loading...</div>;
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
    </div>
  );
}