import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

export function SoulEditor() {
  const [content, setContent] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    apiFetch('/api/soul')
      .then(r => r.json())
      .then(data => {
        setContent(data.content || '');
        setDraft(data.content || '');
      })
      .catch(() => {
        setContent('');
        setDraft('');
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
    } catch (e) {
      console.error('Failed to save SOUL.md', e);
    }
    setSaving(false);
  };

  if (content === null) {
    return <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>{t('loading_configs')}</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', color: 'var(--text-primary)', marginBottom: '4px' }}>
            SOUL.md
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
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
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
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
          setDirty(val !== content);
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
          fontFamily: 'var(--font-mono)',
          fontSize: '13px',
          lineHeight: '1.6',
          resize: 'vertical',
          outline: 'none',
          boxSizing: 'border-box',
          tabSize: 2,
        }}
        spellcheck={false}
      />

      {dirty && (
        <div style={{ fontSize: '10px', color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
          ● unsaved changes
        </div>
      )}
    </div>
  );
}
