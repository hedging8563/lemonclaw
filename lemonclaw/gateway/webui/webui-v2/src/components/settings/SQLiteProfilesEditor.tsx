import { useEffect, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { editorStyles as S, MOBILE_BREAKPOINT, srOnly } from './SettingsEditorShared';

interface Props {
  profiles: Record<string, string>;
  onChange: (profiles: Record<string, string>) => void;
}

function ProfileRow({
  name,
  value,
  onRename,
  onUpdate,
  onDelete,
}: {
  name: string;
  value: string;
  onRename: (nextName: string) => void;
  onUpdate: (nextValue: string) => void;
  onDelete: () => void;
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, 0.8fr) minmax(0, 1.2fr) auto', gap: '8px', alignItems: 'start', marginBottom: '10px' }}>
      <div>
        <label style={S.label}>{t('sqlite_profiles_name_label')}</label>
        <input style={S.input as any} type="text" value={name} placeholder={t('sqlite_profiles_name_placeholder')} onInput={(e) => onRename((e.target as HTMLInputElement).value)} />
      </div>
      <div>
        <label style={S.label}>{t('sqlite_profiles_path_label')}</label>
        <input style={S.input as any} type="text" value={value} placeholder={'/var/lib/lemonclaw/app.db'} onInput={(e) => onUpdate((e.target as HTMLInputElement).value)} />
      </div>
      <div style={{ paddingTop: '22px' }}>
        <button type="button" style={{ ...S.deleteBtn, border: '1px solid var(--border)' }} onClick={onDelete} aria-label={t('sqlite_profiles_delete')} title={t('sqlite_profiles_delete')}>
          ×
        </button>
      </div>
    </div>
  );
}

export function SQLiteProfilesEditor({ profiles, onChange }: Props) {
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
    const next: Record<string, string> = {};
    for (const [name, value] of Object.entries(profiles)) {
      next[name === currentName ? trimmed : name] = value;
    }
    onChange(next);
  };

  const updateValue = (name: string, nextValue: string) => {
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
    onChange({ ...profiles, [trimmed]: '' });
    setNewName('');
  };

  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ marginBottom: '10px', padding: '12px', borderRadius: '6px', background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('sqlite_profiles_title')}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('sqlite_profiles_note')}</div>
      </div>

      {entries.length === 0 && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          {t('sqlite_profiles_empty')}
        </div>
      )}

      <div style={{ marginBottom: '12px' }}>
        {entries.map(([name, value]) => (
          <ProfileRow
            key={name}
            name={name}
            value={value}
            onRename={(nextName) => renameProfile(name, nextName)}
            onUpdate={(nextValue) => updateValue(name, nextValue)}
            onDelete={() => deleteProfile(name)}
          />
        ))}
      </div>

      <div style={{ display: 'flex', gap: '8px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
        <label htmlFor="sqlite-profile-name" style={srOnly}>{t('sqlite_profiles_name_placeholder')}</label>
        <input
          id="sqlite-profile-name"
          name="sqlite_profile_name"
          aria-label={t('sqlite_profiles_name_placeholder')}
          style={S.input as any}
          type="text"
          value={newName}
          placeholder={t('sqlite_profiles_name_placeholder')}
          onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addProfile(); }}
        />
        <button type="button" onClick={addProfile} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto' }}>{t('sqlite_profiles_add')}</button>
      </div>
    </div>
  );
}
