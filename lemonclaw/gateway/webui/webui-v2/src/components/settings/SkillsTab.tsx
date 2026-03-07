import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

const MOBILE_BREAKPOINT = 640;
const srOnly = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

function ExternalLinkButton({ href, label, primary = false }: { href: string; label: string; primary?: boolean }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      title={label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '6px',
        minHeight: '36px',
        padding: '0 14px',
        background: primary ? 'var(--accent)' : 'transparent',
        color: primary ? '#fff' : 'var(--text-primary)',
        border: primary ? 'none' : '1px solid var(--border)',
        borderRadius: '6px',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        fontWeight: primary ? 'bold' : 'normal',
        textDecoration: 'none',
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
    >
      <span>{label}</span>
      <span aria-hidden="true">↗</span>
    </a>
  );
}

function InstallHint({ isMobile }: { isMobile: boolean }) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const tooltipId = 'skills-install-hint';

  useEffect(() => {
    if (!show) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setShow(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShow(false);
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [show]);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        onClick={() => setShow(!show)}
        onMouseEnter={() => !isMobile && setShow(true)}
        onMouseLeave={() => !isMobile && setShow(false)}
        aria-label={t('supported_formats')}
        aria-expanded={show}
        aria-controls={tooltipId}
        style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '50%', width: '24px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer', fontFamily: 'var(--font-mono)', flexShrink: 0 }}
      >?</button>
      {show && (
        <div id={tooltipId} role="dialog" aria-label={t('supported_formats')} style={{ position: 'absolute', top: '32px', right: 0, zIndex: 50, background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px 12px', width: isMobile ? 'min(300px, calc(100vw - 48px))' : '300px', maxWidth: 'calc(100vw - 48px)', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ color: 'var(--text-primary)', fontSize: '12px', fontWeight: 'bold', marginBottom: '2px' }}>{t('supported_formats')}</div>
            <code style={{ color: 'var(--teal)', overflowWrap: 'anywhere' }}>npx skills add owner/repo --skill name</code>
            <code style={{ color: 'var(--teal)', overflowWrap: 'anywhere' }}>owner/repo/skill-name</code>
            <code style={{ color: 'var(--teal)', overflowWrap: 'anywhere' }}>https://skills.sh/owner/repo/skill</code>
            <code style={{ color: 'var(--teal)', overflowWrap: 'anywhere' }}>https://github.com/owner/repo</code>
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
  const [installError, setInstallError] = useState('');
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
      }
    };
    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
  }, []);

  const load = async () => {
    try {
      const res = await apiFetch('/api/settings/skills');
      const data = await res.json();
      setSkills(data.skills || []);
    } catch (e) {
      console.error('Failed to load skills', e);
    }
  };

  useEffect(() => { load(); }, []);

  const handleInstall = async () => {
    if (!installUrl) return;
    setLoading(true);
    setInstallError('');
    try {
      await apiFetch('/api/settings/skills', { method: 'POST', body: JSON.stringify({ url: installUrl }) });
      setInstallUrl('');
      await load();
    } catch (e: any) {
      setInstallError((t('install_failed') + (e.message || '')).trim());
    } finally {
      setLoading(false);
    }
  };

  const toggleSkill = async (name: string, enabled: boolean) => {
    await apiFetch(`/api/settings/skills/${encodeURIComponent(name)}`, { method: 'PATCH', body: JSON.stringify({ enabled: !enabled }) });
    await load();
  };

  const deleteSkill = async (name: string) => {
    if (!confirm(t('confirm_delete_skill').replace('{name}', name))) return;
    await apiFetch(`/api/settings/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await load();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', padding: isMobile ? '12px' : '14px', display: 'flex', flexDirection: isMobile ? 'column' : 'row', justifyContent: 'space-between', alignItems: isMobile ? 'stretch' : 'center', gap: '12px' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-primary)', marginBottom: '4px' }}>{t('skills_discovery_title')}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>{t('skills_discovery_note')}</div>
        </div>
        <ExternalLinkButton href="https://skills.sh" label={t('skills_discovery_action')} primary />
      </div>

      <div style={{ display: 'flex', gap: '8px', alignItems: 'stretch', minHeight: '36px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
        <label htmlFor="skills-install-input" style={srOnly}>{t('skill_placeholder')}</label>
        <input
          id="skills-install-input"
          name="skills_install_input"
          aria-label={t('skill_placeholder')}
          placeholder={t('skill_placeholder')}
          value={installUrl}
          onInput={e => { setInstallUrl((e.target as HTMLInputElement).value); if (installError) setInstallError(''); }}
          style={{ flex: '1 1 260px', minWidth: 0, background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '0 16px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', outline: 'none', transition: 'border-color 0.2s', height: '36px', boxSizing: 'border-box' }}
          onFocus={e => (e.target as HTMLInputElement).style.borderColor = 'var(--accent)'}
          onBlur={e => (e.target as HTMLInputElement).style.borderColor = 'var(--border)'}
        />
        <div style={{ display: 'flex', alignItems: 'center', height: '36px' }}>
          <InstallHint isMobile={isMobile} />
        </div>
        <button
          onClick={handleInstall}
          disabled={loading || !installUrl}
          style={{ background: loading || !installUrl ? 'var(--bg-tertiary)' : 'var(--accent)', color: loading || !installUrl ? 'var(--text-muted)' : '#fff', border: 'none', borderRadius: '6px', padding: isMobile ? '0 16px' : '0 24px', fontWeight: 'bold', cursor: loading || !installUrl ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontSize: '13px', transition: 'all 0.2s', height: '36px', boxSizing: 'border-box', width: isMobile ? '100%' : 'auto' }}
        >
          {loading ? t('installing') : t('install')}
        </button>
      </div>

      {installError && (
        <div role="alert" style={{ fontSize: '12px', color: 'var(--error)', fontFamily: 'var(--font-mono)', padding: '10px 12px', background: 'rgba(255, 68, 68, 0.08)', border: '1px solid rgba(255, 68, 68, 0.24)', borderRadius: '6px' }}>
          {installError}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {skills.map((skill) => (
          <div key={skill.name} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: isMobile ? 'stretch' : 'center', flexDirection: isMobile ? 'column' : 'row', gap: '12px' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ overflowWrap: 'anywhere' }}>{skill.name}</span>
                <span style={{ fontSize: '9px', padding: '2px 4px', background: 'var(--bg-tertiary)', borderRadius: '2px', color: 'var(--text-muted)' }}>{skill.source}</span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.5 }}>{skill.description}</div>
            </div>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexShrink: 0, justifyContent: isMobile ? 'space-between' : 'flex-end' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: skill.enabled ? 'var(--teal)' : 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', userSelect: 'none', transition: 'color 0.2s' }}>
                <input type="checkbox" checked={skill.enabled} onChange={() => toggleSkill(skill.name, skill.enabled)} style={{ width: '14px', height: '14px', accentColor: 'var(--teal)', cursor: 'pointer' }} />
                {t('enabled')}
              </label>
              {skill.source !== 'builtin' && (
                <button
                  onClick={() => deleteSkill(skill.name)}
                  aria-label={t('delete_plugin')}
                  style={{ background: 'transparent', border: '1px solid transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255, 68, 68, 0.1)'; e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.borderColor = 'rgba(255, 68, 68, 0.3)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'transparent'; }}
                  title={t('delete_plugin')}
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
