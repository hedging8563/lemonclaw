import { useEffect, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { editorStyles as S, MOBILE_BREAKPOINT, srOnly } from './SettingsEditorShared';

interface PostgresProfile {
  host?: string;
  port?: number;
  dbname?: string;
  user?: string;
  password?: string;
  sslmode?: string;
}

interface Props {
  profiles: Record<string, PostgresProfile>;
  onChange: (profiles: Record<string, PostgresProfile>) => void;
}

function ProfileCard({
  name,
  profile,
  onRename,
  onUpdate,
  onDelete,
}: {
  name: string;
  profile: PostgresProfile;
  onRename: (nextName: string) => void;
  onUpdate: (nextValue: PostgresProfile) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const setField = (key: keyof PostgresProfile, value: string | number) => {
    onUpdate({ ...profile, [key]: value });
  };

  return (
    <div style={S.card}>
      <div style={S.headerRow}>
        <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} style={S.headerButton}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 'bold', overflowWrap: 'anywhere' }}>{name}</span>
            <span style={S.tag('green')}>{profile.host || 'postgres'}</span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {(profile.dbname || t('postgres_profiles_dbname_placeholder'))}
            </span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px', flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>
        </button>
        <button type="button" style={S.deleteBtn} onClick={(e) => { e.stopPropagation(); onDelete(); }} aria-label={t('postgres_profiles_delete')} title={t('postgres_profiles_delete')}>
          ×
        </button>
      </div>
      {expanded && (
        <div style={S.cardBody as any}>
          <div>
            <label style={S.label}>{t('postgres_profiles_name_label')}</label>
            <input style={S.input as any} type="text" value={name} placeholder={t('postgres_profiles_name_placeholder')} onInput={(e) => onRename((e.target as HTMLInputElement).value)} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 120px', gap: '10px' }}>
            <div>
              <label style={S.label}>{t('postgres_profiles_host_label')}</label>
              <input style={S.input as any} type="text" value={profile.host || ''} placeholder={'db.example.internal'} onInput={(e) => setField('host', (e.target as HTMLInputElement).value)} />
            </div>
            <div>
              <label style={S.label}>{t('postgres_profiles_port_label')}</label>
              <input style={S.input as any} type="number" value={profile.port ?? 5432} placeholder={'5432'} onInput={(e) => setField('port', Number((e.target as HTMLInputElement).value) || 5432)} />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '10px' }}>
            <div>
              <label style={S.label}>{t('postgres_profiles_dbname_label')}</label>
              <input style={S.input as any} type="text" value={profile.dbname || ''} placeholder={t('postgres_profiles_dbname_placeholder')} onInput={(e) => setField('dbname', (e.target as HTMLInputElement).value)} />
            </div>
            <div>
              <label style={S.label}>{t('postgres_profiles_user_label')}</label>
              <input style={S.input as any} type="text" value={profile.user || ''} placeholder={'readonly_user'} onInput={(e) => setField('user', (e.target as HTMLInputElement).value)} />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 160px', gap: '10px' }}>
            <div>
              <label style={S.label}>{t('postgres_profiles_password_label')}</label>
              <input style={S.input as any} type="text" value={profile.password || ''} placeholder={'••••••••'} onInput={(e) => setField('password', (e.target as HTMLInputElement).value)} />
            </div>
            <div>
              <label style={S.label}>{t('postgres_profiles_sslmode_label')}</label>
              <input style={S.input as any} type="text" value={profile.sslmode || 'prefer'} placeholder={'prefer'} onInput={(e) => setField('sslmode', (e.target as HTMLInputElement).value)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function PostgresProfilesEditor({ profiles, onChange }: Props) {
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
    const next: Record<string, PostgresProfile> = {};
    for (const [name, value] of Object.entries(profiles)) {
      next[name === currentName ? trimmed : name] = value;
    }
    onChange(next);
  };

  const updateValue = (name: string, nextValue: PostgresProfile) => {
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
    onChange({ ...profiles, [trimmed]: { port: 5432, sslmode: 'prefer' } });
    setNewName('');
  };

  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ marginBottom: '10px', padding: '12px', borderRadius: '6px', background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('postgres_profiles_title')}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('postgres_profiles_note')}</div>
      </div>

      {entries.length === 0 && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          {t('postgres_profiles_empty')}
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
        <label htmlFor="postgres-profile-name" style={srOnly}>{t('postgres_profiles_name_placeholder')}</label>
        <input
          id="postgres-profile-name"
          name="postgres_profile_name"
          aria-label={t('postgres_profiles_name_placeholder')}
          style={S.input as any}
          type="text"
          value={newName}
          placeholder={t('postgres_profiles_name_placeholder')}
          onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addProfile(); }}
        />
        <button type="button" onClick={addProfile} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto' }}>{t('postgres_profiles_add')}</button>
      </div>
    </div>
  );
}
