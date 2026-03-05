import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';

export function SkillsTab() {
  const [skills, setSkills] = useState<any[]>([]);
  const [installUrl, setInstallUrl] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    try {
      const res = await apiFetch('/api/settings/skills');
      const data = await res.json();
      setSkills(data.skills || []);
    } catch (e) {
      console.error("Failed to load skills", e);
    }
  };

  useEffect(() => { load(); }, []);

  const handleInstall = async () => {
    if (!installUrl) return;
    setLoading(true);
    try {
      await apiFetch('/api/settings/skills', { method: 'POST', body: JSON.stringify({ url: installUrl }) });
      setInstallUrl('');
      await load();
    } catch(e: any) {
      alert("Install failed: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleSkill = async (name: string, enabled: boolean) => {
    await apiFetch(`/api/settings/skills/${name}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) });
    await load();
  };

  const deleteSkill = async (name: string) => {
    if (!confirm(`Delete skill ${name}?`)) return;
    await apiFetch(`/api/settings/skills/${name}`, { method: 'DELETE' });
    await load();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', gap: '8px' }}>
        <input 
          placeholder="GitHub URL to install skill..." 
          value={installUrl} 
          onInput={e => setInstallUrl((e.target as HTMLInputElement).value)} 
          style={{ flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '8px 12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none' }} 
        />
        <button onClick={handleInstall} disabled={loading} style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: '4px', padding: '0 20px', fontWeight: 'bold', cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
          {loading ? 'INSTALLING...' : 'INSTALL'}
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {skills.map(s => (
          <div key={s.name} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                {s.name} 
                <span style={{ fontSize: '9px', padding: '2px 4px', background: 'var(--bg-tertiary)', borderRadius: '2px', color: 'var(--text-muted)' }}>{s.source}</span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>{s.description}</div>
            </div>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
                <input type="checkbox" checked={s.enabled} onChange={() => toggleSkill(s.name, s.enabled)} />
                ENABLED
              </label>
              {s.source !== 'builtin' && (
                <button onClick={() => deleteSkill(s.name)} style={{ background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '18px', lineHeight: 1 }} title="Delete">×</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}