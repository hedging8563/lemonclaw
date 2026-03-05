import { useEffect, useState } from 'preact/hooks';
import { memory, loadMemory } from '../../stores/memory';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

export function MemoryPanel() {
  const [editingEntity, setEditingEntity] = useState<string | null>(null);
  const [editBody, setEditBody] = useState('');
  const [editingCore, setEditingCore] = useState(false);
  const [coreDraft, setCoreDraft] = useState('');

  useEffect(() => {
    loadMemory();
  }, []);

  const handleSaveEntity = async (name: string) => {
    await apiFetch(`/api/memory/entities/${name}`, {
      method: 'PATCH',
      body: JSON.stringify({ body: editBody })
    });
    setEditingEntity(null);
    await loadMemory();
  };

  const handleSaveCore = async () => {
    await apiFetch(`/api/memory/core`, {
      method: 'PATCH',
      body: JSON.stringify({ content: coreDraft })
    });
    setEditingCore(false);
    await loadMemory();
  };

  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--purple)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px' }}>
        // MEMORY
      </div>
      
      {!memory.value ? (
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Loading memory...</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          
          {/* Core Memory */}
          {memory.value.core && (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                [CORE]
                {!editingCore && <button onClick={() => { setEditingCore(true); setCoreDraft(memory.value.core); }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>EDIT</button>}
              </div>
              {editingCore ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea value={coreDraft} onInput={e => setCoreDraft((e.target as HTMLTextAreaElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '6px', fontSize: '11px', fontFamily: 'var(--font-ui)', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button onClick={() => setEditingCore(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>CANCEL</button>
                    <button onClick={handleSaveCore} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>SAVE</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingCore(true); setCoreDraft(memory.value.core); }}>
                  {memory.value.core}
                </div>
              )}
            </div>
          )}

          {/* Entities */}
          {memory.value.entities?.map((e: any) => (
            <div key={e.name} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                {e.name}
                {editingEntity !== e.name && <button onClick={() => { setEditingEntity(e.name); setEditBody(e.body); }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>EDIT</button>}
              </div>
              
              {editingEntity === e.name ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea value={editBody} onInput={evt => setEditBody((evt.target as HTMLTextAreaElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '6px', fontSize: '11px', fontFamily: 'var(--font-ui)', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button onClick={() => setEditingEntity(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>CANCEL</button>
                    <button onClick={() => handleSaveEntity(e.name)} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>SAVE</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingEntity(e.name); setEditBody(e.body); }}>
                  {e.body}
                </div>
              )}
            </div>
          ))}
          {(!memory.value.entities || memory.value.entities.length === 0) && !memory.value.core && (
            <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
               <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_memory')}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}