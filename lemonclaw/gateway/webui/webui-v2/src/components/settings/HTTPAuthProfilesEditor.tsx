import { useEffect, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { editorStyles as S, linesToDict, dictToLines, MOBILE_BREAKPOINT, srOnly } from './SettingsEditorShared';

interface Props {
  profiles: Record<string, Record<string, string>>;
  onChange: (profiles: Record<string, Record<string, string>>) => void;
}

function ProfileCard({
  name,
  headers,
  onUpdate,
  onDelete,
}: {
  name: string;
  headers: Record<string, string>;
  onUpdate: (value: Record<string, string>) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [headersText, setHeadersText] = useState(dictToLines(headers));

  useEffect(() => {
    setHeadersText(dictToLines(headers));
  }, [JSON.stringify(headers)]);

  return (
    <div style={S.card}>
      <div style={S.headerRow}>
        <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} style={S.headerButton}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 'bold', overflowWrap: 'anywhere' }}>{name}</span>
            <span style={S.tag('blue')}>{Object.keys(headers || {}).length} {t('http_auth_profiles_headers_badge')}</span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px', flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>
        </button>
        <button type="button" style={S.deleteBtn} onClick={(e) => { e.stopPropagation(); onDelete(); }} aria-label={t('http_auth_profiles_delete')} title={t('http_auth_profiles_delete')}>
          ×
        </button>
      </div>
      {expanded && (
        <div style={S.cardBody as any}>
          <div>
            <label style={S.label}>{t('http_auth_profiles_headers_label')}</label>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px', lineHeight: 1.5 }}>{t('http_auth_profiles_headers_help')}</div>
            <textarea
              style={S.textarea as any}
              value={headersText}
              placeholder={'Authorization=Bearer sk-xxx\nX-API-Key=demo'}
              onInput={(e) => setHeadersText((e.target as HTMLTextAreaElement).value)}
              onBlur={() => onUpdate(linesToDict(headersText))}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export function HTTPAuthProfilesEditor({ profiles, onChange }: Props) {
  const [newName, setNewName] = useState('');
  const [adding, setAdding] = useState(false);
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

  const handleUpdate = (name: string, value: Record<string, string>) => {
    onChange({ ...profiles, [name]: value });
  };

  const handleDelete = (name: string) => {
    const next = { ...profiles };
    delete next[name];
    onChange(next);
  };

  const handleAdd = () => {
    const trimmed = newName.trim();
    if (!trimmed || profiles[trimmed]) return;
    onChange({ ...profiles, [trimmed]: {} });
    setNewName('');
    setAdding(false);
  };

  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{ marginBottom: '10px', padding: '12px', borderRadius: '6px', background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{t('http_auth_profiles_title')}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('http_auth_profiles_note')}</div>
      </div>

      {entries.length === 0 && !adding && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          {t('http_auth_profiles_empty')}
        </div>
      )}

      {entries.map(([name, headers]) => (
        <ProfileCard key={name} name={name} headers={headers} onUpdate={(value) => handleUpdate(name, value)} onDelete={() => handleDelete(name)} />
      ))}

      {adding ? (
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
          <label htmlFor="http-auth-profile-name" style={srOnly}>{t('http_auth_profiles_name_placeholder')}</label>
          <input
            id="http-auth-profile-name"
            name="http_auth_profile_name"
            aria-label={t('http_auth_profiles_name_placeholder')}
            style={S.input as any}
            type="text"
            value={newName}
            placeholder={t('http_auth_profiles_name_placeholder')}
            onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAdd();
              if (e.key === 'Escape') {
                setAdding(false);
                setNewName('');
              }
            }}
            autoFocus
          />
          <button onClick={handleAdd} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto' }}>{t('http_auth_profiles_add')}</button>
          <button onClick={() => { setAdding(false); setNewName(''); }} style={{ padding: '8px 12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', width: isMobile ? '100%' : 'auto' }}>{t('btn_cancel')}</button>
        </div>
      ) : (
        <button type="button" style={S.addBtn} onClick={() => setAdding(true)}>{t('http_auth_profiles_add_profile')}</button>
      )}
    </div>
  );
}
