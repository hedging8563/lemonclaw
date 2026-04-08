import { useEffect, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { editorStyles as S, MOBILE_BREAKPOINT, srOnly } from './SettingsEditorShared';

interface GitAuthProfile {
  username?: string;
  password?: string;
}

interface Props {
  profiles: Record<string, GitAuthProfile>;
  onChange: (profiles: Record<string, GitAuthProfile>) => void;
}

function ProfileCard({
  name,
  profile,
  onRename,
  onUpdate,
  onDelete,
}: {
  name: string;
  profile: GitAuthProfile;
  onRename: (nextName: string) => void;
  onUpdate: (nextValue: GitAuthProfile) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const setField = (key: keyof GitAuthProfile, value: string) => {
    onUpdate({ ...profile, [key]: value });
  };

  return (
    <div style={S.card}>
      <div style={S.headerRow}>
        <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} style={S.headerButton}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '15px', fontWeight: 'bold', overflowWrap: 'anywhere' }}>{name}</span>
            <span style={S.tag('blue')}>{profile.username || t('git_auth_profiles_username_placeholder')}</span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '15px', flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>
        </button>
        <button type="button" style={S.deleteBtn} onClick={(e) => { e.stopPropagation(); onDelete(); }} aria-label={t('git_auth_profiles_delete')} title={t('git_auth_profiles_delete')}>
          ×
        </button>
      </div>
      {expanded && (
        <div style={S.cardBody as any}>
          <div>
            <label style={S.label}>{t('git_auth_profiles_name_label')}</label>
            <input style={S.input as any} type="text" value={name} placeholder={t('git_auth_profiles_name_placeholder')} onInput={(e) => onRename((e.target as HTMLInputElement).value)} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '10px' }}>
            <div>
              <label style={S.label}>{t('git_auth_profiles_username_label')}</label>
              <input
                style={S.input as any}
                type="text"
                value={profile.username || ''}
                placeholder={t('git_auth_profiles_username_placeholder')}
                onInput={(e) => setField('username', (e.target as HTMLInputElement).value)}
              />
            </div>
            <div>
              <label style={S.label}>{t('git_auth_profiles_password_label')}</label>
              <input
                style={S.input as any}
                type="text"
                value={profile.password || ''}
                placeholder={t('git_auth_profiles_password_placeholder')}
                onInput={(e) => setField('password', (e.target as HTMLInputElement).value)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function GitAuthProfilesEditor({ profiles, onChange }: Props) {
  const [newName, setNewName] = useState('');
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    };
    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
  }, []);

  const entries = Object.entries(profiles || {});

  const renameProfile = (currentName: string, nextName: string) => {
    const trimmed = nextName.trim();
    if (!trimmed || trimmed === currentName || profiles[trimmed]) return;
    const next: Record<string, GitAuthProfile> = {};
    for (const [name, value] of Object.entries(profiles)) {
      next[name === currentName ? trimmed : name] = value;
    }
    onChange(next);
  };

  const updateValue = (name: string, nextValue: GitAuthProfile) => {
    onChange({ ...profiles, [name]: nextValue });
  };

  const deleteProfile = (name: string) => {
    const next = { ...profiles };
    delete next[name];
    onChange(next);
  };

  const addProfile = () => {
    const trimmed = newName.trim();
    if (!trimmed || profiles[trimmed]) return;
    onChange({ ...profiles, [trimmed]: { username: 'x-access-token', password: '' } });
    setNewName('');
  };

  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ marginBottom: '10px', padding: '12px', borderRadius: '6px', background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: '15px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', marginBottom: '4px' }}>{t('git_auth_profiles_title')}</div>
        <div style={{ fontSize: '15px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('git_auth_profiles_note')}</div>
      </div>

      {entries.length === 0 && (
        <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          {t('git_auth_profiles_empty')}
        </div>
      )}

      <div style={{ marginBottom: '12px' }}>
        {entries.map(([name, profile]) => (
          <ProfileCard
            key={name}
            name={name}
            profile={profile}
            onRename={(nextName) => renameProfile(name, nextName)}
            onUpdate={(nextValue) => updateValue(name, nextValue)}
            onDelete={() => deleteProfile(name)}
          />
        ))}
      </div>

      <div style={{ display: 'flex', gap: '8px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
        <label htmlFor="git-auth-profile-name" style={srOnly}>{t('git_auth_profiles_name_placeholder')}</label>
        <input
          id="git-auth-profile-name"
          name="git_auth_profile_name"
          aria-label={t('git_auth_profiles_name_placeholder')}
          style={S.input as any}
          type="text"
          value={newName}
          placeholder={t('git_auth_profiles_name_placeholder')}
          onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addProfile(); }}
        />
        <button type="button" onClick={addProfile} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-ui)', fontSize: '15px', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto' }}>{t('git_auth_profiles_add')}</button>
      </div>
    </div>
  );
}
