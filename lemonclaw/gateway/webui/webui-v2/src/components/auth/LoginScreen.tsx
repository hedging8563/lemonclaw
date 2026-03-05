import { useState } from 'preact/hooks';
import { login } from '../../stores/auth';

export function LoginScreen() {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');

  const handleLogin = async (e: Event) => {
    e.preventDefault();
    try {
      await login(token);
    } catch (err: any) {
      setError(err.message || 'Login failed');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: '24px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '28px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
        Lemon<span style={{ color: 'var(--purple)', textShadow: '0 0 12px var(--purple-dim)' }}>Claw</span>
      </div>
      <form onSubmit={handleLogin} style={{ display: 'flex', gap: '8px' }}>
        <input 
          type="password" 
          placeholder="Gateway Token..." 
          value={token}
          onInput={(e) => setToken((e.target as HTMLInputElement).value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px 16px', color: 'var(--text-primary)', outline: 'none', fontFamily: 'var(--font-mono)' }}
        />
        <button type="submit" style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: '6px', padding: '0 16px', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
          LOGIN
        </button>
      </form>
      {error && <div style={{ color: 'var(--error)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>{error}</div>}
    </div>
  );
}