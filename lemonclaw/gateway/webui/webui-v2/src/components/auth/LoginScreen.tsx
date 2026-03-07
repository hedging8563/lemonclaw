import { useEffect, useState } from 'preact/hooks';
import { login } from '../../stores/auth';
import { t } from '../../stores/i18n';

export function LoginScreen() {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get('token');
    if (t) {
      history.replaceState({}, '', window.location.pathname);
      setToken(t);
      login(t).catch((err) => setError(err.message || 'Login failed'));
    }
  }, []);

  const handleLogin = async (e: Event) => {
    e.preventDefault();
    try {
      await login(token);
    } catch (err: any) {
      setError(err.message || 'Login failed');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', padding: '24px 16px', gap: '24px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'clamp(24px, 7vw, 28px)', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.5px', textAlign: 'center' }}>
        Lemon<span style={{ color: 'var(--purple)', textShadow: '0 0 12px var(--purple-dim)' }}>Claw</span>
      </div>
      <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: 'min(420px, 100%)' }}>
        <input
          type="password"
          name="token"
          autoComplete="current-password"
          placeholder={t('login_token_placeholder')}
          value={token}
          onInput={(e) => setToken((e.target as HTMLInputElement).value)}
          style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px 16px', color: 'var(--text-primary)', outline: 'none', fontFamily: 'var(--font-mono)' }}
        />

        <button type="submit" style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: '6px', padding: '12px 16px', cursor: 'pointer', fontFamily: 'var(--font-mono)', width: '100%' }}>
          {t('login_action')}
        </button>
      </form>
      {error && <div style={{ color: 'var(--error)', fontSize: '12px', fontFamily: 'var(--font-mono)', width: 'min(420px, 100%)', textAlign: 'center', wordBreak: 'break-word' }}>{error}</div>}
    </div>
  );
}
