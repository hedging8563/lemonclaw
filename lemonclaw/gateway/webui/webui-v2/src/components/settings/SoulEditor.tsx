import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

export const SOUL_DRAFT_STORAGE_KEY = 'lemonclaw:soulDraft';

type SoulDraftSnapshot = {
  content: string;
  draft: string;
};

function readStoredSoulDraft(): SoulDraftSnapshot | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(SOUL_DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SoulDraftSnapshot>;
    if (typeof parsed.content !== 'string' || typeof parsed.draft !== 'string') return null;
    return { content: parsed.content, draft: parsed.draft };
  } catch {
    return null;
  }
}

function writeStoredSoulDraft(snapshot: SoulDraftSnapshot | null): void {
  if (typeof localStorage === 'undefined') return;
  if (!snapshot) {
    localStorage.removeItem(SOUL_DRAFT_STORAGE_KEY);
    return;
  }
  localStorage.setItem(SOUL_DRAFT_STORAGE_KEY, JSON.stringify(snapshot));
}

export function hasUnsavedSoulDraft(): boolean {
  const snapshot = readStoredSoulDraft();
  return Boolean(snapshot && snapshot.draft !== snapshot.content);
}

export function discardSoulDraft(): void {
  writeStoredSoulDraft(null);
}

export function SoulEditor() {
  const [content, setContent] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    apiFetch('/api/soul')
      .then(r => r.json())
      .then(data => {
        const nextContent = data.content || '';
        const stored = readStoredSoulDraft();
        setContent(nextContent);
        if (stored) {
          setDraft(stored.draft);
          setDirty(stored.draft !== nextContent);
        } else {
          setDraft(nextContent);
          setDirty(false);
        }
      })
      .catch(() => {
        const stored = readStoredSoulDraft();
        setContent('');
        setDraft(stored?.draft || '');
        setDirty(Boolean(stored && stored.draft !== ''));
      });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiFetch('/api/soul', {
        method: 'PATCH',
        body: JSON.stringify({ content: draft }),
      });
      setContent(draft);
      setDirty(false);
      writeStoredSoulDraft(null);
    } catch (e) {
      console.error('Failed to save SOUL.md', e);
    }
    setSaving(false);
  };

  if (content === null) {
    return <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', fontSize: '15px' }}>{t('loading_configs')}</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: '24px', color: 'var(--text-primary)', marginBottom: '12px', fontWeight: 'bold', letterSpacing: '-0.02em', overflowWrap: 'anywhere' }}>
            {t('tab_soul')}
          </div>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--text-muted)', marginBottom: '6px' }}>
            SOUL.md
          </div>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)' }}>
            {t('soul_desc')}
          </div>
        </div>
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          style={{
            padding: '8px 20px',
            background: dirty ? 'var(--accent)' : 'var(--bg-tertiary)',
            border: 'none',
            borderRadius: '6px',
            color: '#fff',
            cursor: dirty ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--font-ui)',
            fontSize: '15px',
            fontWeight: 'bold',
            opacity: saving ? 0.6 : 1,
            transition: 'all 0.2s',
          }}
        >
          {saving ? '...' : t('btn_save')}
        </button>
      </div>

      <textarea
        value={draft}
        onInput={(e) => {
          const val = (e.target as HTMLTextAreaElement).value;
          setDraft(val);
          const nextDirty = val !== content;
          setDirty(nextDirty);
          writeStoredSoulDraft(nextDirty ? { content: content || '', draft: val } : null);
        }}
        style={{
          flex: 1,
          minHeight: '400px',
          width: '100%',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          color: 'var(--text-primary)',
          padding: '16px',
          borderRadius: '6px',
          fontFamily: 'var(--font-ui)',
          fontSize: '15px',
          lineHeight: '1.6',
          resize: 'vertical',
          outline: 'none',
          boxSizing: 'border-box',
          tabSize: 2,
        }}
        spellcheck={false}
      />

      {dirty && (
        <div style={{ fontSize: '15px', color: 'var(--accent)', fontFamily: 'var(--font-ui)' }}>
          ● unsaved changes
        </div>
      )}
    </div>
  );
}
