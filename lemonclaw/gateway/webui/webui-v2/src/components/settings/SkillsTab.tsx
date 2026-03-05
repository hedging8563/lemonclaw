import { useEffect, useState, useRef } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

function InstallHint() {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        onClick={() => setShow(!show)}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        aria-label={t('supported_formats')}
        style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '50%', width: '24px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer', fontFamily: 'var(--font-mono)', flexShrink: 0 }}
      >?</button>
      {show && (
        <div style={{ position: 'absolute', top: '32px', right: 0, zIndex: 50, background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px 12px', width: '300px', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ color: 'var(--text-primary)', fontSize: '12px', fontWeight: 'bold', marginBottom: '2px' }}>{t('supported_formats')}</div>
            <code style={{ color: 'var(--teal)' }}>npx skills add owner/repo --skill name</code>
            <code style={{ color: 'var(--teal)' }}>owner/repo/skill-name</code>
            <code style={{ color: 'var(--teal)' }}>https://skills.sh/owner/repo/skill</code>
            <code style={{ color: 'var(--teal)' }}>https://github.com/owner/repo</code>
          </div>
        </div>
      )}
    </div>
  );
}

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
      alert(t('install_failed') + e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleSkill = async (name: string, enabled: boolean) => {
    await apiFetch(`/api/settings/skills/${name}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) });
    await load();
  };

  const deleteSkill = async (name: string) => {
    if (!confirm(t('confirm_delete_skill').replace('{name}', name))) return;
    await apiFetch(`/api/settings/skills/${name}`, { method: 'DELETE' });
    await load();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'stretch', height: '36px' }}>
        <input
          placeholder={t('skill_placeholder')}
          value={installUrl}
          onInput={e => setInstallUrl((e.target as HTMLInputElement).value)}
          style={{ flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '0 16px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', outline: 'none', transition: 'border-color 0.2s', height: '100%', boxSizing: 'border-box' }}
          onFocus={e => (e.target as HTMLInputElement).style.borderColor = 'var(--accent)'}
          onBlur={e => (e.target as HTMLInputElement).style.borderColor = 'var(--border)'}
        />
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <InstallHint />
        </div>
        <button onClick={handleInstall} disabled={loading || !installUrl} style={{ background: loading || !installUrl ? 'var(--bg-tertiary)' : 'var(--accent)', color: loading || !installUrl ? 'var(--text-muted)' : '#fff', border: 'none', borderRadius: '6px', padding: '0 24px', fontWeight: 'bold', cursor: loading || !installUrl ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontSize: '13px', transition: 'all 0.2s', height: '100%', boxSizing: 'border-box' }}>
          {loading ? t('installing') : t('install')}
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
            <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexShrink: 0 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: s.enabled ? 'var(--teal)' : 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', userSelect: 'none', transition: 'color 0.2s' }}>
                <input 
                  type="checkbox" 
                  checked={s.enabled} 
                  onChange={() => toggleSkill(s.name, s.enabled)} 
                  style={{ width: '14px', height: '14px', accentColor: 'var(--teal)', cursor: 'pointer' }}
                />
                {t('enabled')}
              </label>
              {s.source !== 'builtin' && (
                <button 
                  onClick={() => deleteSkill(s.name)} 
                  style={{ background: 'transparent', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255, 68, 68, 0.1)'; e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.borderColor = 'rgba(255, 68, 68, 0.3)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'transparent'; }}
                  title="Delete Plugin"
                >
                  🗑️
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}