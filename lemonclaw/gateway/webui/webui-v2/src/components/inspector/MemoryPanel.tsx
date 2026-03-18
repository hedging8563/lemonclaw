import { useEffect, useMemo, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';
import { activeKnowledgeChunks, activeKnowledgeDocument, activeKnowledgeFacts, knowledgeDocuments, knowledgeError, knowledgeResults, knowledgeSummary, loadKnowledge, loadKnowledgeDocument, searchKnowledge, selectedKnowledgeResultType, selectedKnowledgeSourceType } from '../../stores/knowledge';
import { memory, memoryError, type MemoryEntityRecord, loadMemory, type MemoryRuleRecord } from '../../stores/memory';

function pillStyle(active = false) {
  return {
    padding: '4px 8px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(124, 58, 237, 0.1)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
  } as const;
}

function formatTime(value?: number) {
  const stamp = Number(value || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MemoryPanel() {
  const [editingEntity, setEditingEntity] = useState<string | null>(null);
  const [editBody, setEditBody] = useState('');
  const [editingCore, setEditingCore] = useState(false);
  const [coreDraft, setCoreDraft] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState('note');
  const [newKeywords, setNewKeywords] = useState('');
  const [newBody, setNewBody] = useState('');
  const [creatingKnowledge, setCreatingKnowledge] = useState(false);
  const [knowledgeTitle, setKnowledgeTitle] = useState('');
  const [knowledgeSource, setKnowledgeSource] = useState('');
  const [knowledgeType, setKnowledgeType] = useState('url');
  const [knowledgeNote, setKnowledgeNote] = useState('');
  const [knowledgeContent, setKnowledgeContent] = useState('');
  const [knowledgeRefreshHours, setKnowledgeRefreshHours] = useState('0');
  const [knowledgeQuery, setKnowledgeQuery] = useState('');
  const [editingKnowledgeId, setEditingKnowledgeId] = useState<string | null>(null);
  const [editKnowledgeTitle, setEditKnowledgeTitle] = useState('');
  const [editKnowledgeSource, setEditKnowledgeSource] = useState('');
  const [editKnowledgeType, setEditKnowledgeType] = useState('url');
  const [editKnowledgeNote, setEditKnowledgeNote] = useState('');
  const [editKnowledgeContent, setEditKnowledgeContent] = useState('');
  const [editKnowledgeRefreshHours, setEditKnowledgeRefreshHours] = useState('0');

  useEffect(() => {
    loadMemory();
    loadKnowledge();
  }, []);

  const handleSaveEntity = async (name: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/memory/entities/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: editBody })
      });
      setEditingEntity(null);
      await loadMemory();
    } catch (e: any) {
      setSaveError(e.message || t('memory_save_failed'));
    }
  };

  const handleSaveCore = async () => {
    setSaveError(null);
    try {
      await apiFetch(`/api/memory/core`, {
        method: 'PATCH',
        body: JSON.stringify({ content: coreDraft })
      });
      setEditingCore(false);
      await loadMemory();
    } catch (e: any) {
      setSaveError(e.message || t('memory_save_failed'));
    }
  };

  const handleCreateEntity = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/memory/entities', {
        method: 'POST',
        body: JSON.stringify({
          name: newName,
          type: newType,
          keywords: newKeywords,
          body: newBody,
        })
      });
      setCreating(false);
      setNewName('');
      setNewType('note');
      setNewKeywords('');
      setNewBody('');
      await loadMemory();
    } catch (e: any) {
      setSaveError(e.message || t('memory_create_failed'));
    }
  };

  const handleCreateKnowledge = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/knowledge/documents', {
        method: 'POST',
        body: JSON.stringify({
          title: knowledgeTitle,
          source: knowledgeSource,
          source_type: knowledgeType,
          note: knowledgeNote,
          content: knowledgeContent,
          refresh_interval_hours: Number(knowledgeRefreshHours || 0),
        }),
      });
      setCreatingKnowledge(false);
      setKnowledgeTitle('');
      setKnowledgeSource('');
      setKnowledgeType('url');
      setKnowledgeNote('');
      setKnowledgeContent('');
      setKnowledgeRefreshHours('0');
      await loadKnowledge();
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_create_failed'));
    }
  };

  const handleIngestKnowledge = async (docId: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}/ingest`, { method: 'POST' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_ingest_failed'));
    }
  };

  const handleDeleteKnowledge = async (docId: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' });
      await loadKnowledge();
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_delete_failed'));
    }
  };

  const handleEditKnowledge = async (docId: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          title: editKnowledgeTitle,
          source: editKnowledgeSource,
          source_type: editKnowledgeType,
          note: editKnowledgeNote,
          content: editKnowledgeContent,
          refresh_interval_hours: Number(editKnowledgeRefreshHours || 0),
        }),
      });
      setEditingKnowledgeId(null);
      await loadKnowledge();
      await loadKnowledgeDocument(docId);
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_create_failed'));
    }
  };

  const handleSearchKnowledge = async () => {
    setSaveError(null);
    try {
      await searchKnowledge(knowledgeQuery);
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_search_failed'));
    }
  };

  const handleReingestAll = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/knowledge/reingest', { method: 'POST' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_ingest_failed'));
    }
  };

  const handleRefreshDue = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/knowledge/refresh-due', { method: 'POST' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (e: any) {
      setSaveError(e.message || t('knowledge_ingest_failed'));
    }
  };

  const snapshot = memory.value;
  const query = filter.trim().toLowerCase();
  const filteredEntities = useMemo(() => (
    (snapshot?.entities || []).filter((item: MemoryEntityRecord) => {
      if (!query) return true;
      return [
        item.name,
        item.type,
        ...(item.keywords || []),
        item.body,
      ].join(' ').toLowerCase().includes(query);
    })
  ), [snapshot, query]);
  const filteredRules = useMemo(() => (
    (snapshot?.rules || []).filter((item: MemoryRuleRecord) => {
      if (!query) return true;
      return [
        item.trigger,
        item.lesson,
        item.action,
      ].join(' ').toLowerCase().includes(query);
    })
  ), [snapshot, query]);
  const filteredHistory = useMemo(() => (
    (snapshot?.history || []).filter((entry: string) => !query || entry.toLowerCase().includes(query))
  ), [snapshot, query]);

  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--purple)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px' }}>
        // {t('memory_title')}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '10px' }}>
        <button onClick={() => void loadMemory()} style={pillStyle()}>{t('memory_refresh')}</button>
        <button onClick={() => void navigator.clipboard.writeText(JSON.stringify(snapshot || {}, null, 2))} style={pillStyle()}>{t('memory_copy')}</button>
        <button onClick={() => downloadJson('memory-snapshot.json', snapshot || {})} style={pillStyle()}>{t('memory_export_json')}</button>
        <button onClick={() => setCreating((value) => !value)} style={pillStyle(creating)}>{t('memory_new_card')}</button>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px' }}>
        <div style={pillStyle()}>{t('memory_count_entities')}: {snapshot?.entities?.length || 0}</div>
        <div style={pillStyle()}>{t('memory_count_rules')}: {snapshot?.rules?.length || 0}</div>
        <div style={pillStyle()}>{t('memory_count_history')}: {snapshot?.history?.length || 0}</div>
        <div style={pillStyle()}>{t('memory_count_indexed')}: {snapshot?.search_index?.last_indexed_docs || 0}</div>
      </div>
      <input
        value={filter}
        onInput={(e) => setFilter((e.target as HTMLInputElement).value)}
        placeholder={t('memory_filter_placeholder')}
        style={{ width: '100%', marginBottom: '10px', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }}
      />
      {(saveError || memoryError.value || knowledgeError.value) && <div style={{ fontSize: '11px', color: 'var(--error)', fontFamily: 'var(--font-mono)', marginBottom: '8px', padding: '6px 8px', background: 'rgba(255,68,68,0.1)', borderRadius: '4px' }}>{saveError || memoryError.value || knowledgeError.value}</div>}
      
      {!snapshot ? (
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_loading')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)' }}>{t('knowledge_sources')}</div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button onClick={() => void handleReingestAll()} style={pillStyle()}>{t('knowledge_reingest_all')}</button>
                <button onClick={() => void handleRefreshDue()} style={pillStyle()}>{t('knowledge_refresh_due')}</button>
                <button onClick={() => setCreatingKnowledge((value) => !value)} style={pillStyle(creatingKnowledge)}>{t('knowledge_add_source')}</button>
              </div>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
              <span style={pillStyle()}>{t('knowledge_count_sources')}: {knowledgeSummary.value?.total || 0}</span>
              <span style={pillStyle()}>{t('knowledge_count_types')}: {Object.keys(knowledgeSummary.value?.by_type || {}).length}</span>
              <span style={pillStyle()}>{t('knowledge_count_due')}: {knowledgeSummary.value?.due_count || 0}</span>
            </div>
            {creatingKnowledge && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '8px' }}>
                <input value={knowledgeTitle} onInput={(e) => setKnowledgeTitle((e.target as HTMLInputElement).value)} placeholder={t('knowledge_title')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                <select value={knowledgeType} onInput={(e) => setKnowledgeType((e.target as HTMLSelectElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }}>
                  <option value="url">url</option>
                  <option value="file">file</option>
                  <option value="manual">manual</option>
                </select>
                <input value={knowledgeSource} onInput={(e) => setKnowledgeSource((e.target as HTMLInputElement).value)} placeholder={t('knowledge_source')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                <textarea value={knowledgeNote} onInput={(e) => setKnowledgeNote((e.target as HTMLTextAreaElement).value)} placeholder={t('knowledge_note')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', minHeight: '72px', resize: 'vertical', outline: 'none' }} />
                <input value={knowledgeRefreshHours} onInput={(e) => setKnowledgeRefreshHours((e.target as HTMLInputElement).value)} placeholder={t('knowledge_refresh_hours')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                {knowledgeType === 'manual' && (
                  <textarea value={knowledgeContent} onInput={(e) => setKnowledgeContent((e.target as HTMLTextAreaElement).value)} placeholder={t('knowledge_content')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button onClick={() => setCreatingKnowledge(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                  <button onClick={handleCreateKnowledge} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('knowledge_create')}</button>
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
              <input value={knowledgeQuery} onInput={(e) => setKnowledgeQuery((e.target as HTMLInputElement).value)} placeholder={t('knowledge_search_placeholder')} style={{ flex: 1, background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
              <button onClick={() => void handleSearchKnowledge()} style={pillStyle()}>{t('knowledge_search')}</button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
              <span style={{ ...pillStyle(), color: 'var(--text-muted)' }}>{t('knowledge_filter_source')}</span>
              {['', 'url', 'file', 'manual'].map((value) => (
                <button key={`src-${value || 'all'}`} onClick={() => void searchKnowledge(knowledgeQuery, { source_type: value })} style={pillStyle(selectedKnowledgeSourceType.value === value)}>{value || 'all'}</button>
              ))}
              <span style={{ ...pillStyle(), color: 'var(--text-muted)' }}>{t('knowledge_filter_result')}</span>
              {['', 'chunk', 'fact'].map((value) => (
                <button key={`res-${value || 'all'}`} onClick={() => void searchKnowledge(knowledgeQuery, { result_type: value })} style={pillStyle(selectedKnowledgeResultType.value === value)}>{value || 'all'}</button>
              ))}
            </div>
            {knowledgeDocuments.value.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {knowledgeDocuments.value.map((doc) => (
                  <div key={doc.doc_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '6px', alignItems: 'center' }}>
                      <div style={{ minWidth: 0, cursor: 'pointer' }} onClick={() => void loadKnowledgeDocument(doc.doc_id)}>
                        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.title || doc.source}</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', wordBreak: 'break-word' }}>{doc.source}</div>
                      </div>
                      <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                        <button onClick={() => {
                          setEditingKnowledgeId(doc.doc_id);
                          setEditKnowledgeTitle(doc.title || '');
                          setEditKnowledgeSource(doc.source || '');
                          setEditKnowledgeType(doc.source_type || 'url');
                          setEditKnowledgeNote(doc.note || '');
                          setEditKnowledgeContent((doc as any).content || '');
                          setEditKnowledgeRefreshHours(String(doc.refresh_interval_hours || 0));
                        }} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)', borderRadius: '4px', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('knowledge_edit')}</button>
                        <button onClick={() => void handleIngestKnowledge(doc.doc_id)} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--teal)', borderRadius: '4px', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('knowledge_ingest')}</button>
                        <button onClick={() => void handleDeleteKnowledge(doc.doc_id)} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: '4px', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('knowledge_remove')}</button>
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      <span style={pillStyle()}>{doc.source_type}</span>
                      <span style={pillStyle()}>{doc.status || 'registered'}</span>
                      <span style={pillStyle()}>{`${t('knowledge_chunk_count')}:${doc.chunk_count || 0}`}</span>
                      <span style={pillStyle()}>{`${t('knowledge_refresh_hours')}:${doc.refresh_interval_hours || 0}`}</span>
                      <span style={pillStyle()}>{formatTime(doc.updated_at_ms)}</span>
                      {doc.ingested_at_ms ? <span style={pillStyle()}>{`${t('knowledge_ingested_at')}:${formatTime(doc.ingested_at_ms)}`}</span> : null}
                      {doc.next_refresh_at_ms ? <span style={pillStyle()}>{`${t('knowledge_next_refresh')}:${formatTime(doc.next_refresh_at_ms)}`}</span> : null}
                    </div>
                    {doc.note && <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '6px', whiteSpace: 'pre-wrap' }}>{doc.note}</div>}
                    {doc.last_error && <div style={{ fontSize: '11px', color: 'var(--error)', marginTop: '6px', whiteSpace: 'pre-wrap' }}>{doc.last_error}</div>}
                    {editingKnowledgeId === doc.doc_id && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--border)' }}>
                        <input value={editKnowledgeTitle} onInput={(e) => setEditKnowledgeTitle((e.target as HTMLInputElement).value)} placeholder={t('knowledge_title')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                        <select value={editKnowledgeType} onInput={(e) => setEditKnowledgeType((e.target as HTMLSelectElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }}>
                          <option value="url">url</option>
                          <option value="file">file</option>
                          <option value="manual">manual</option>
                        </select>
                        <input value={editKnowledgeSource} onInput={(e) => setEditKnowledgeSource((e.target as HTMLInputElement).value)} placeholder={t('knowledge_source')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                        <textarea value={editKnowledgeNote} onInput={(e) => setEditKnowledgeNote((e.target as HTMLTextAreaElement).value)} placeholder={t('knowledge_note')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', minHeight: '72px', resize: 'vertical', outline: 'none' }} />
                        <input value={editKnowledgeRefreshHours} onInput={(e) => setEditKnowledgeRefreshHours((e.target as HTMLInputElement).value)} placeholder={t('knowledge_refresh_hours')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
                        {editKnowledgeType === 'manual' && (
                          <textarea value={editKnowledgeContent} onInput={(e) => setEditKnowledgeContent((e.target as HTMLTextAreaElement).value)} placeholder={t('knowledge_content')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                        )}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                          <button onClick={() => setEditingKnowledgeId(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                          <button onClick={() => void handleEditKnowledge(doc.doc_id)} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('knowledge_update')}</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_empty')}</div>
            )}
            {activeKnowledgeDocument.value && (
              <div style={{ marginTop: '10px', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>
                <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('knowledge_detail')}</div>
                <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>{activeKnowledgeDocument.value.title || activeKnowledgeDocument.value.source}</div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px', wordBreak: 'break-word' }}>{activeKnowledgeDocument.value.source}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                  <span style={pillStyle()}>{activeKnowledgeDocument.value.source_type || '—'}</span>
                  <span style={pillStyle()}>{activeKnowledgeDocument.value.status || 'registered'}</span>
                  <span style={pillStyle()}>{`${t('knowledge_chunk_count')}:${activeKnowledgeDocument.value.chunk_count || 0}`}</span>
                  <span style={pillStyle()}>{`facts:${activeKnowledgeDocument.value.fact_count || 0}`}</span>
                </div>
                {activeKnowledgeDocument.value.note && <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '8px', whiteSpace: 'pre-wrap' }}>{activeKnowledgeDocument.value.note}</div>}
                {activeKnowledgeDocument.value.metadata && Object.keys(activeKnowledgeDocument.value.metadata).length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                    {Object.entries(activeKnowledgeDocument.value.metadata).map(([key, value]) => (
                      <span key={key} style={pillStyle()}>{`${key}:${String(value)}`}</span>
                    ))}
                  </div>
                )}
                <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('knowledge_chunks')}</div>
                {activeKnowledgeChunks.value.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {activeKnowledgeChunks.value.map((chunk) => (
                      <div key={chunk.chunk_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                          <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{chunk.chunk_id}</div>
                          <span style={pillStyle()}>{formatTime(chunk.updated_at_ms)}</span>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{chunk.text || '—'}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>
                )}
                <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginTop: '10px', marginBottom: '8px' }}>{t('knowledge_facts')}</div>
                {activeKnowledgeFacts.value.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {activeKnowledgeFacts.value.map((fact) => (
                      <div key={fact.fact_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                          <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{fact.fact_id}</div>
                          <span style={pillStyle()}>{formatTime(fact.updated_at_ms)}</span>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{fact.claim || '—'}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>
                )}
              </div>
            )}
            <div style={{ marginTop: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('knowledge_search_results')}</div>
              {knowledgeResults.value.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {knowledgeResults.value.map((item, idx) => (
                    <div key={`${item.doc_id || 'result'}-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{item.title || item.doc_id || '—'}</div>
                        <span style={pillStyle()}>{`score:${item.score || 0}`}</span>
                      </div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', wordBreak: 'break-word' }}>{item.source || '—'}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{item.snippet || '—'}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>
              )}
            </div>
          </div>

          {creating && (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)' }}>{t('memory_new_card')}</div>
              <input value={newName} onInput={(e) => setNewName((e.target as HTMLInputElement).value)} placeholder={t('memory_name')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
              <input value={newType} onInput={(e) => setNewType((e.target as HTMLInputElement).value)} placeholder={t('memory_type')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
              <input value={newKeywords} onInput={(e) => setNewKeywords((e.target as HTMLInputElement).value)} placeholder={t('memory_keywords')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', outline: 'none' }} />
              <textarea value={newBody} onInput={(e) => setNewBody((e.target as HTMLTextAreaElement).value)} placeholder={t('memory_body')} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', borderRadius: '6px', padding: '8px 10px', fontSize: '12px', minHeight: '100px', resize: 'vertical', outline: 'none' }} />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button onClick={() => setCreating(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                <button onClick={handleCreateEntity} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('memory_create')}</button>
              </div>
            </div>
          )}

          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('memory_search_index')}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px', fontSize: '11px' }}>
              <div><span style={{ color: 'var(--text-muted)' }}>{t('memory_search_available')}:</span> <span style={{ color: snapshot.search_index?.available ? 'var(--success)' : 'var(--error)' }}>{snapshot.search_index?.available ? t('common_yes') : t('common_no')}</span></div>
              <div><span style={{ color: 'var(--text-muted)' }}>{t('memory_search_db')}:</span> <span style={{ color: 'var(--text-primary)' }}>{snapshot.search_index?.db_exists ? t('memory_search_ready') : t('memory_search_empty')}</span></div>
              <div><span style={{ color: 'var(--text-muted)' }}>{t('memory_search_last_op')}:</span> <span style={{ color: 'var(--text-primary)' }}>{snapshot.search_index?.last_operation || '—'}</span></div>
              <div><span style={{ color: 'var(--text-muted)' }}>{t('memory_search_indexed')}:</span> <span style={{ color: 'var(--text-primary)' }}>{snapshot.search_index?.last_indexed_docs || 0}</span></div>
              <div style={{ gridColumn: '1 / -1' }}><span style={{ color: 'var(--text-muted)' }}>{t('memory_search_last_updated')}:</span> <span style={{ color: 'var(--text-primary)' }}>{formatTime(snapshot.search_index?.last_updated_ms)}</span></div>
              {snapshot.search_index?.last_error && (
                <div style={{ gridColumn: '1 / -1', color: 'var(--error)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{t('memory_search_last_error')}:</span> {snapshot.search_index?.last_error}
                </div>
              )}
            </div>
          </div>
          
          {/* Core Memory */}
          {snapshot.core && (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                {t('memory_core')}
                {!editingCore && <button onClick={() => { setEditingCore(true); setCoreDraft(snapshot.core || ''); }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_edit')}</button>}
              </div>
              {editingCore ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea value={coreDraft} onInput={e => setCoreDraft((e.target as HTMLTextAreaElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '6px', fontSize: '11px', fontFamily: 'var(--font-ui)', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button onClick={() => setEditingCore(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                    <button onClick={handleSaveCore} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('memory_save')}</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingCore(true); setCoreDraft(snapshot.core || ''); }}>
                  {snapshot.core}
                </div>
              )}
            </div>
          )}

          {snapshot.today ? (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('memory_today')}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>{snapshot.today}</div>
            </div>
          ) : (
            <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_empty_today')}</div>
          )}

          {snapshot.long_term && (
            <details style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)' }}>{t('memory_legacy_long_term')}</summary>
              <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap', marginTop: '8px' }}>{snapshot.long_term}</div>
            </details>
          )}

          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('memory_entities')}</div>
            {filteredEntities.map((e: MemoryEntityRecord) => (
            <div key={e.name} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                <span>{e.name}</span>
                {editingEntity !== e.name && <button onClick={() => { setEditingEntity(e.name); setEditBody(e.body); }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_edit')}</button>}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                {e.type && <span style={pillStyle()}>{e.type}</span>}
                {typeof e.access_count === 'number' && <span style={pillStyle()}>{`access:${e.access_count}`}</span>}
                {(e.keywords || []).slice(0, 6).map((item) => <span key={item} style={pillStyle()}>{item}</span>)}
              </div>
              
              {editingEntity === e.name ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea value={editBody} onInput={evt => setEditBody((evt.target as HTMLTextAreaElement).value)} style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '6px', fontSize: '11px', fontFamily: 'var(--font-ui)', minHeight: '120px', resize: 'vertical', outline: 'none' }} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button onClick={() => setEditingEntity(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                    <button onClick={() => handleSaveEntity(e.name)} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('memory_save')}</button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingEntity(e.name); setEditBody(e.body); }}>
                  {e.body}
                </div>
              )}
            </div>
            ))}
            {(!filteredEntities || filteredEntities.length === 0) && (
              <div style={{ padding: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
                 <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_memory')}</div>
              </div>
            )}
          </div>

          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('memory_rules')}</div>
            {filteredRules.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {filteredRules.map((rule, idx) => (
                  <div key={`${rule.trigger || 'rule'}-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', marginBottom: '4px' }}>{rule.trigger || '—'}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-primary)', marginBottom: '4px' }}>{rule.lesson || '—'}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{rule.action || '—'}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_empty_rules')}</div>
            )}
          </div>

          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', marginBottom: '8px' }}>{t('memory_history')}</div>
            {filteredHistory.length > 0 ? (
              <details open>
                <summary style={{ cursor: 'pointer', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>{`${filteredHistory.length} ${t('memory_history_entries')}`}</summary>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {filteredHistory.slice(0, 12).map((entry, idx) => (
                    <div key={`history-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                      {entry}
                    </div>
                  ))}
                </div>
              </details>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_empty_history')}</div>
            )}
          </div>

          {(!snapshot.entities || snapshot.entities.length === 0) && !snapshot.core && !snapshot.today && (!snapshot.rules || snapshot.rules.length === 0) && (
            <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
               <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_memory')}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
