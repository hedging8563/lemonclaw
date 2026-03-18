import { useEffect, useMemo, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';
import {
  activeMemoryPanelTab,
  activeKnowledgeChunks,
  activeKnowledgeDocument,
  activeKnowledgeFacts,
  filterKnowledgeDocuments,
  knowledgeDocuments,
  knowledgeError,
  knowledgeResults,
  knowledgeSummary,
  loadKnowledge,
  loadKnowledgeDocument,
  partitionKnowledgeDocuments,
  searchKnowledge,
  selectedKnowledgeResultType,
  selectedKnowledgeSourceType,
  type KnowledgeDocumentRecord,
  type MemoryPanelTab,
  type KnowledgeView,
} from '../../stores/knowledge';
import { loadMemory, memory, memoryError, type MemoryEntityRecord, type MemoryRuleRecord } from '../../stores/memory';

const panelStyle = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, var(--bg-primary) 100%)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '12px',
  boxShadow: '0 12px 26px rgba(0,0,0,0.14)',
} as const;

const inputStyle = {
  width: '100%',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  borderRadius: '10px',
  padding: '10px 12px',
  fontSize: '12px',
  outline: 'none',
} as const;

const textareaStyle = {
  ...inputStyle,
  minHeight: '96px',
  resize: 'vertical',
} as const;

const sectionTitleStyle = {
  fontSize: '12px',
  fontFamily: 'var(--font-mono)',
  color: 'var(--purple)',
} as const;

function sectionShellStyle(maxHeight?: number) {
  return {
    display: 'grid',
    gap: '8px',
    ...(maxHeight ? { maxHeight: `${maxHeight}px`, overflowY: 'auto', paddingRight: '4px' } : {}),
  } as const;
}

function pillStyle(active = false) {
  return {
    padding: '6px 10px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(255, 107, 53, 0.12)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    cursor: 'pointer',
  } as const;
}

function actionButtonStyle(color = 'var(--text-secondary)') {
  return {
    background: 'transparent',
    border: '1px solid var(--border)',
    color,
    borderRadius: '999px',
    cursor: 'pointer',
    fontSize: '10px',
    padding: '6px 10px',
  } as const;
}

function formatTime(value?: number | null) {
  const stamp = Number(value || 0);
  if (!stamp) return '—';
  try {
    return new Date(stamp).toLocaleString([], {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
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

function renderAccordionSection(
  title: string,
  count: number | null,
  children: any,
  defaultOpen = false,
  maxHeight = 260,
) {
  return (
    <details open={defaultOpen} style={panelStyle}>
      <summary style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', listStyle: 'none' }}>
        <span style={sectionTitleStyle}>{title}</span>
        {typeof count === 'number' ? <span style={pillStyle(count > 0)}>{count}</span> : null}
      </summary>
      <div style={{ marginTop: '10px', ...sectionShellStyle(maxHeight) }}>{children}</div>
    </details>
  );
}

export function MemoryPanel() {
  const [panelExpanded, setPanelExpanded] = useState(true);
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
  const [knowledgeView, setKnowledgeView] = useState<KnowledgeView>('all');
  const [editingKnowledgeId, setEditingKnowledgeId] = useState<string | null>(null);
  const [editKnowledgeTitle, setEditKnowledgeTitle] = useState('');
  const [editKnowledgeSource, setEditKnowledgeSource] = useState('');
  const [editKnowledgeType, setEditKnowledgeType] = useState('url');
  const [editKnowledgeNote, setEditKnowledgeNote] = useState('');
  const [editKnowledgeContent, setEditKnowledgeContent] = useState('');
  const [editKnowledgeRefreshHours, setEditKnowledgeRefreshHours] = useState('0');

  useEffect(() => {
    void loadMemory();
    void loadKnowledge();
  }, []);

  useEffect(() => {
    const hasIngesting = knowledgeDocuments.value.some((doc) => doc.status === 'ingesting');
    if (!hasIngesting) return;
    const timer = window.setInterval(() => {
      void loadKnowledge();
      if (activeKnowledgeDocument.value?.doc_id) {
        void loadKnowledgeDocument(activeKnowledgeDocument.value.doc_id);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [knowledgeDocuments.value.map((doc) => `${doc.doc_id}:${doc.status || ''}`).join('|'), activeKnowledgeDocument.value?.doc_id]);

  const snapshot = memory.value;
  const activeTab = activeMemoryPanelTab.value;
  const activeDoc = activeKnowledgeDocument.value;
  const activeChunks = activeKnowledgeChunks.value;
  const activeFacts = activeKnowledgeFacts.value;
  const query = filter.trim().toLowerCase();

  const filteredEntities = useMemo(
    () =>
      (snapshot?.entities || []).filter((item: MemoryEntityRecord) => {
        if (!query) return true;
        return [item.name, item.type, ...(item.keywords || []), item.body]
          .join(' ')
          .toLowerCase()
          .includes(query);
      }),
    [snapshot, query],
  );

  const filteredRules = useMemo(
    () =>
      (snapshot?.rules || []).filter((item: MemoryRuleRecord) => {
        if (!query) return true;
        return [item.trigger, item.lesson, item.action].join(' ').toLowerCase().includes(query);
      }),
    [snapshot, query],
  );

  const visibleKnowledgeDocs = useMemo(
    () => filterKnowledgeDocuments(knowledgeDocuments.value, knowledgeView),
    [knowledgeView, knowledgeDocuments.value],
  );

  const groupedKnowledgeDocs = useMemo(
    () => partitionKnowledgeDocuments(knowledgeDocuments.value),
    [knowledgeDocuments.value],
  );

  const knowledgeDocumentMap = useMemo(
    () => new Map(knowledgeDocuments.value.map((doc) => [doc.doc_id, doc])),
    [knowledgeDocuments.value],
  );

  const openKnowledgeDetail = (docId: string) => {
    void loadKnowledgeDocument(docId);
    activeMemoryPanelTab.value = 'detail';
  };

  const resetKnowledgeCreateForm = () => {
    setCreatingKnowledge(false);
    setKnowledgeTitle('');
    setKnowledgeSource('');
    setKnowledgeType('url');
    setKnowledgeNote('');
    setKnowledgeContent('');
    setKnowledgeRefreshHours('0');
  };

  const resetKnowledgeEditForm = () => {
    setEditingKnowledgeId(null);
    setEditKnowledgeTitle('');
    setEditKnowledgeSource('');
    setEditKnowledgeType('url');
    setEditKnowledgeNote('');
    setEditKnowledgeContent('');
    setEditKnowledgeRefreshHours('0');
  };

  const handleSaveEntity = async (name: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/memory/entities/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: editBody }),
      });
      setEditingEntity(null);
      await loadMemory();
    } catch (error: any) {
      setSaveError(error.message || t('memory_save_failed'));
    }
  };

  const handleSaveCore = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/memory/core', {
        method: 'PATCH',
        body: JSON.stringify({ content: coreDraft }),
      });
      setEditingCore(false);
      await loadMemory();
    } catch (error: any) {
      setSaveError(error.message || t('memory_save_failed'));
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
        }),
      });
      setCreating(false);
      setNewName('');
      setNewType('note');
      setNewKeywords('');
      setNewBody('');
      await loadMemory();
    } catch (error: any) {
      setSaveError(error.message || t('memory_create_failed'));
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
      resetKnowledgeCreateForm();
      await loadKnowledge();
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_create_failed'));
    }
  };

  const handleIngestKnowledge = async (docId: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}/ingest?wait=0`, { method: 'POST' });
      await loadKnowledge();
      await loadKnowledgeDocument(docId);
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_ingest_failed'));
    }
  };

  const handleDeleteKnowledge = async (docId: string) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_delete_failed'));
    }
  };

  const handleToggleKnowledgePinned = async (docId: string, pinned: boolean) => {
    setSaveError(null);
    try {
      await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ pinned }),
      });
      await loadKnowledge();
      if (activeDoc?.doc_id === docId) {
        await loadKnowledgeDocument(docId);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_create_failed'));
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
      resetKnowledgeEditForm();
      await loadKnowledge();
      await loadKnowledgeDocument(docId);
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_create_failed'));
    }
  };

  const handleSearchKnowledge = async () => {
    setSaveError(null);
    try {
      await searchKnowledge(knowledgeQuery);
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_search_failed'));
    }
  };

  const handleReingestAll = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/knowledge/reingest?wait=0', { method: 'POST' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_ingest_failed'));
    }
  };

  const handleRefreshDue = async () => {
    setSaveError(null);
    try {
      await apiFetch('/api/knowledge/refresh-due?wait=0', { method: 'POST' });
      await loadKnowledge();
      if (knowledgeQuery.trim()) {
        await searchKnowledge(knowledgeQuery);
      }
    } catch (error: any) {
      setSaveError(error.message || t('knowledge_ingest_failed'));
    }
  };

  const beginKnowledgeEdit = (doc: KnowledgeDocumentRecord) => {
    setEditingKnowledgeId(doc.doc_id);
    setEditKnowledgeTitle(doc.title || '');
    setEditKnowledgeSource(doc.source || '');
    setEditKnowledgeType(doc.source_type || 'url');
    setEditKnowledgeNote(doc.note || '');
    setEditKnowledgeContent((doc as any).content || '');
    setEditKnowledgeRefreshHours(String(doc.refresh_interval_hours || 0));
  };

  const renderKnowledgeForm = (mode: 'create' | 'edit', docId?: string) => {
    const isEdit = mode === 'edit';
    const currentType = isEdit ? editKnowledgeType : knowledgeType;
    const currentTitle = isEdit ? editKnowledgeTitle : knowledgeTitle;
    const currentSource = isEdit ? editKnowledgeSource : knowledgeSource;
    const currentNote = isEdit ? editKnowledgeNote : knowledgeNote;
    const currentContent = isEdit ? editKnowledgeContent : knowledgeContent;
    const currentRefreshHours = isEdit ? editKnowledgeRefreshHours : knowledgeRefreshHours;

    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          marginTop: isEdit ? '8px' : undefined,
          paddingTop: isEdit ? '8px' : undefined,
          borderTop: isEdit ? '1px solid var(--border)' : undefined,
        }}
      >
        <input
          value={currentTitle}
          onInput={(event) =>
            isEdit
              ? setEditKnowledgeTitle((event.target as HTMLInputElement).value)
              : setKnowledgeTitle((event.target as HTMLInputElement).value)
          }
          placeholder={t('knowledge_title')}
          style={inputStyle}
        />
        <select
          value={currentType}
          onInput={(event) =>
            isEdit
              ? setEditKnowledgeType((event.target as HTMLSelectElement).value)
              : setKnowledgeType((event.target as HTMLSelectElement).value)
          }
          style={inputStyle}
        >
          <option value="url">url</option>
          <option value="file">file</option>
          <option value="manual">manual</option>
        </select>
        <input
          value={currentSource}
          onInput={(event) =>
            isEdit
              ? setEditKnowledgeSource((event.target as HTMLInputElement).value)
              : setKnowledgeSource((event.target as HTMLInputElement).value)
          }
          placeholder={t('knowledge_source')}
          style={inputStyle}
        />
        <textarea
          value={currentNote}
          onInput={(event) =>
            isEdit
              ? setEditKnowledgeNote((event.target as HTMLTextAreaElement).value)
              : setKnowledgeNote((event.target as HTMLTextAreaElement).value)
          }
          placeholder={t('knowledge_note')}
          style={{ ...textareaStyle, minHeight: '72px' }}
        />
        <input
          value={currentRefreshHours}
          onInput={(event) =>
            isEdit
              ? setEditKnowledgeRefreshHours((event.target as HTMLInputElement).value)
              : setKnowledgeRefreshHours((event.target as HTMLInputElement).value)
          }
          placeholder={t('knowledge_refresh_hours')}
          style={inputStyle}
        />
        {currentType === 'manual' ? (
          <textarea
            value={currentContent}
            onInput={(event) =>
              isEdit
                ? setEditKnowledgeContent((event.target as HTMLTextAreaElement).value)
                : setKnowledgeContent((event.target as HTMLTextAreaElement).value)
            }
            placeholder={t('knowledge_content')}
            style={{ ...textareaStyle, minHeight: '120px' }}
          />
        ) : null}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <button
            onClick={() => (isEdit ? resetKnowledgeEditForm() : resetKnowledgeCreateForm())}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}
          >
            {t('memory_cancel')}
          </button>
          <button
            onClick={() => {
              if (isEdit && docId) {
                void handleEditKnowledge(docId);
                return;
              }
              void handleCreateKnowledge();
            }}
            style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}
          >
            {isEdit ? t('knowledge_update') : t('knowledge_create')}
          </button>
        </div>
      </div>
    );
  };

  const renderKnowledgeCard = (doc: KnowledgeDocumentRecord) => (
    <div key={doc.doc_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '6px', alignItems: 'center' }}>
        <div
          style={{ minWidth: 0, cursor: 'pointer' }}
          onClick={() => {
            openKnowledgeDetail(doc.doc_id);
          }}
        >
          <div
            style={{
              fontSize: '12px',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {doc.title || doc.source}
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', wordBreak: 'break-word' }}>{doc.source}</div>
        </div>
        <div style={{ display: 'flex', gap: '6px', flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <button onClick={() => beginKnowledgeEdit(doc)} style={actionButtonStyle()}>
            {t('knowledge_edit')}
          </button>
          <button
            onClick={() => void handleToggleKnowledgePinned(doc.doc_id, !doc.pinned)}
            style={actionButtonStyle(doc.pinned ? 'var(--accent)' : 'var(--text-secondary)')}
          >
            {doc.pinned ? t('knowledge_unpin') : t('knowledge_pin')}
          </button>
          <button onClick={() => void handleIngestKnowledge(doc.doc_id)} style={actionButtonStyle('var(--teal)')}>
            {t('knowledge_ingest')}
          </button>
          <button onClick={() => void handleDeleteKnowledge(doc.doc_id)} style={actionButtonStyle('var(--text-muted)')}>
            {t('knowledge_remove')}
          </button>
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        <span style={pillStyle()}>{doc.source_type}</span>
        <span style={pillStyle()}>{doc.status || 'registered'}</span>
        {doc.pinned ? <span style={pillStyle(true)}>{t('knowledge_pin')}</span> : null}
        <span style={pillStyle()}>{`${t('knowledge_chunk_count')}:${doc.chunk_count || 0}`}</span>
        <span style={pillStyle()}>{`${t('knowledge_retrieval_count')}:${doc.retrieval_count || 0}`}</span>
        <span style={pillStyle()}>{`${t('knowledge_refresh_hours')}:${doc.refresh_interval_hours || 0}`}</span>
        <span style={pillStyle()}>{formatTime(doc.updated_at_ms)}</span>
        {doc.ingested_at_ms ? <span style={pillStyle()}>{`${t('knowledge_ingested_at')}:${formatTime(doc.ingested_at_ms)}`}</span> : null}
        {doc.next_refresh_at_ms ? <span style={pillStyle()}>{`${t('knowledge_next_refresh')}:${formatTime(doc.next_refresh_at_ms)}`}</span> : null}
        {doc.last_hit_at_ms ? <span style={pillStyle()}>{`${t('knowledge_last_hit')}:${formatTime(doc.last_hit_at_ms)}`}</span> : null}
      </div>
      {doc.last_hit_query ? (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '6px', whiteSpace: 'pre-wrap' }}>
          {`${t('knowledge_last_query')}: ${doc.last_hit_query}`}
        </div>
      ) : null}
      {doc.note ? <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '6px', whiteSpace: 'pre-wrap' }}>{doc.note}</div> : null}
      {doc.last_error ? <div style={{ fontSize: '11px', color: 'var(--error)', marginTop: '6px', whiteSpace: 'pre-wrap' }}>{doc.last_error}</div> : null}
      {editingKnowledgeId === doc.doc_id ? renderKnowledgeForm('edit', doc.doc_id) : null}
    </div>
  );

  const renderSourcesTab = () => (
    <div style={{ display: 'grid', gap: '10px' }}>
      <div style={panelStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
        <div style={sectionTitleStyle}>{t('knowledge_sources')}</div>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <button onClick={() => void handleReingestAll()} style={pillStyle()}>
            {t('knowledge_reingest_all')}
          </button>
          <button onClick={() => void handleRefreshDue()} style={pillStyle()}>
            {t('knowledge_refresh_due')}
          </button>
          <button onClick={() => setCreatingKnowledge((value) => !value)} style={pillStyle(creatingKnowledge)}>
            {t('knowledge_add_source')}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
        <span style={pillStyle()}>{t('knowledge_count_sources')}: {knowledgeSummary.value?.total || 0}</span>
        <span style={pillStyle()}>{t('knowledge_count_types')}: {Object.keys(knowledgeSummary.value?.by_type || {}).length}</span>
        <span style={pillStyle()}>{t('knowledge_count_due')}: {knowledgeSummary.value?.due_count || 0}</span>
        <span style={pillStyle()}>{t('knowledge_count_pinned')}: {knowledgeSummary.value?.pinned_count || 0}</span>
        <span style={pillStyle()}>{t('knowledge_count_used')}: {knowledgeSummary.value?.used_count || 0}</span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px' }}>
        {([
          ['all', t('knowledge_view_all')],
          ['pinned', t('knowledge_view_pinned')],
          ['used', t('knowledge_view_used')],
          ['due', t('knowledge_view_due')],
          ['ingesting', t('knowledge_view_ingesting')],
        ] as Array<[KnowledgeView, string]>).map(([value, label]) => (
          <button key={value} onClick={() => setKnowledgeView(value)} style={pillStyle(knowledgeView === value)}>
            {label}
          </button>
        ))}
      </div>

      {creatingKnowledge ? <div style={{ marginBottom: '10px' }}>{renderKnowledgeForm('create')}</div> : null}
      </div>

      {knowledgeDocuments.value.length > 0 ? (
        knowledgeView === 'all' ? (
          <>
            {groupedKnowledgeDocs.pinned.length > 0 ? renderAccordionSection(t('knowledge_group_pinned'), groupedKnowledgeDocs.pinned.length, groupedKnowledgeDocs.pinned.map(renderKnowledgeCard), true, 260) : null}
            {groupedKnowledgeDocs.due.length > 0 ? renderAccordionSection(t('knowledge_group_due'), groupedKnowledgeDocs.due.length, groupedKnowledgeDocs.due.map(renderKnowledgeCard), true, 260) : null}
            {groupedKnowledgeDocs.used.length > 0 ? renderAccordionSection(t('knowledge_group_used'), groupedKnowledgeDocs.used.length, groupedKnowledgeDocs.used.map(renderKnowledgeCard), false, 260) : null}
            {groupedKnowledgeDocs.other.length > 0 ? renderAccordionSection(t('knowledge_group_other'), groupedKnowledgeDocs.other.length, groupedKnowledgeDocs.other.map(renderKnowledgeCard), false, 300) : null}
          </>
        ) : (
          renderAccordionSection(t('knowledge_sources'), visibleKnowledgeDocs.length, visibleKnowledgeDocs.map(renderKnowledgeCard), true, 360)
        )
      ) : (
        <div style={{ ...panelStyle, fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_empty')}</div>
      )}
    </div>
  );

  const renderSearchTab = () => (
    <div style={panelStyle}>
      <div style={{ marginBottom: '8px', ...sectionTitleStyle }}>{t('knowledge_search_results')}</div>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
        <input
          value={knowledgeQuery}
          onInput={(event) => setKnowledgeQuery((event.target as HTMLInputElement).value)}
          placeholder={t('knowledge_search_placeholder')}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button onClick={() => void handleSearchKnowledge()} style={pillStyle()}>
          {t('knowledge_search')}
        </button>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
        <span style={{ ...pillStyle(), color: 'var(--text-muted)', cursor: 'default' }}>{t('knowledge_filter_source')}</span>
        {['', 'url', 'file', 'manual'].map((value) => (
          <button
            key={`src-${value || 'all'}`}
            onClick={() => void searchKnowledge(knowledgeQuery, { source_type: value })}
            style={pillStyle(selectedKnowledgeSourceType.value === value)}
          >
            {value || 'all'}
          </button>
        ))}
        <span style={{ ...pillStyle(), color: 'var(--text-muted)', cursor: 'default' }}>{t('knowledge_filter_result')}</span>
        {['', 'chunk', 'fact'].map((value) => (
          <button
            key={`res-${value || 'all'}`}
            onClick={() => void searchKnowledge(knowledgeQuery, { result_type: value })}
            style={pillStyle(selectedKnowledgeResultType.value === value)}
          >
            {value || 'all'}
          </button>
        ))}
      </div>

      {knowledgeResults.value.length > 0 ? (
        <div style={sectionShellStyle(420)}>
          {knowledgeResults.value.map((item, idx) => {
            const linkedDoc = item.doc_id ? knowledgeDocumentMap.get(item.doc_id) : null;
            return (
              <div
                key={`${item.doc_id || 'result'}-${idx}`}
                onClick={() => {
                  if (item.doc_id) openKnowledgeDetail(item.doc_id);
                }}
                style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', cursor: item.doc_id ? 'pointer' : 'default' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                    {item.title || item.doc_id || '—'}
                  </div>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {item.doc_id ? (
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          openKnowledgeDetail(item.doc_id);
                        }}
                        style={actionButtonStyle()}
                      >
                        {t('open')}
                      </button>
                    ) : null}
                    {item.doc_id && linkedDoc ? (
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleToggleKnowledgePinned(item.doc_id, !linkedDoc.pinned);
                        }}
                        style={actionButtonStyle(linkedDoc.pinned ? 'var(--accent)' : 'var(--text-secondary)')}
                      >
                        {linkedDoc.pinned ? t('knowledge_unpin') : t('knowledge_pin')}
                      </button>
                    ) : null}
                    {item.page_label ? <span style={pillStyle()}>{item.page_label}</span> : null}
                    <span style={pillStyle()}>{`score:${item.score || 0}`}</span>
                  </div>
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', wordBreak: 'break-word' }}>{item.source || '—'}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{item.snippet || '—'}</div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>
      )}
    </div>
  );

  const renderDetailTab = () => (
    <div style={panelStyle}>
      {activeDoc ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div>
            <div style={{ marginBottom: '8px', ...sectionTitleStyle }}>{t('knowledge_detail')}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '4px' }}>
              {activeDoc.title || activeDoc.source}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px', wordBreak: 'break-word' }}>{activeDoc.source}</div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <button
                onClick={() => void handleToggleKnowledgePinned(activeDoc.doc_id, !activeDoc.pinned)}
                style={pillStyle(Boolean(activeDoc.pinned))}
              >
                {activeDoc.pinned ? t('knowledge_unpin') : t('knowledge_pin')}
              </button>
              <button onClick={() => void handleIngestKnowledge(activeDoc.doc_id)} style={pillStyle()}>
                {t('knowledge_ingest')}
              </button>
              <button onClick={() => beginKnowledgeEdit(activeDoc)} style={pillStyle(editingKnowledgeId === activeDoc.doc_id)}>
                {t('knowledge_edit')}
              </button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
              <span style={pillStyle()}>{activeDoc.source_type || '—'}</span>
              <span style={pillStyle()}>{activeDoc.status || 'registered'}</span>
              <span style={pillStyle()}>{`${t('knowledge_chunk_count')}:${activeDoc.chunk_count || 0}`}</span>
              <span style={pillStyle()}>{`facts:${activeDoc.fact_count || 0}`}</span>
              <span style={pillStyle()}>{`${t('knowledge_retrieval_count')}:${activeDoc.retrieval_count || 0}`}</span>
              {activeDoc.next_refresh_at_ms ? <span style={pillStyle()}>{`${t('knowledge_next_refresh')}:${formatTime(activeDoc.next_refresh_at_ms)}`}</span> : null}
            </div>
            {activeDoc.last_hit_at_ms ? (
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                {`${t('knowledge_last_hit')}: ${formatTime(activeDoc.last_hit_at_ms)}`}
              </div>
            ) : null}
            {activeDoc.last_hit_query ? (
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '8px', whiteSpace: 'pre-wrap' }}>
                {`${t('knowledge_last_query')}: ${activeDoc.last_hit_query}`}
              </div>
            ) : null}
            {activeDoc.note ? (
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '8px', whiteSpace: 'pre-wrap' }}>{activeDoc.note}</div>
            ) : null}
            {activeDoc.metadata && Object.keys(activeDoc.metadata).length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                {Object.entries(activeDoc.metadata).map(([key, value]) => (
                  <span key={key} style={pillStyle()}>{`${key}:${String(value)}`}</span>
                ))}
              </div>
            ) : null}
            {editingKnowledgeId === activeDoc.doc_id ? renderKnowledgeForm('edit', activeDoc.doc_id) : null}
          </div>

          {renderAccordionSection(
            t('knowledge_chunks'),
            activeChunks.length,
            activeChunks.length > 0 ? activeChunks.map((chunk) => (
              <div key={chunk.chunk_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{chunk.chunk_id}</div>
                    {chunk.page_label ? <span style={pillStyle()}>{chunk.page_label}</span> : null}
                  </div>
                  <span style={pillStyle()}>{formatTime(chunk.updated_at_ms)}</span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{chunk.text || '—'}</div>
              </div>
            )) : <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>,
            activeChunks.length <= 3,
            260,
          )}

          {renderAccordionSection(
            t('knowledge_facts'),
            activeFacts.length,
            activeFacts.length > 0 ? activeFacts.map((fact) => (
              <div key={fact.fact_id} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{fact.fact_id}</div>
                    {fact.page_label ? <span style={pillStyle()}>{fact.page_label}</span> : null}
                  </div>
                  <span style={pillStyle()}>{formatTime(fact.updated_at_ms)}</span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{fact.claim || '—'}</div>
              </div>
            )) : <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_search_empty')}</div>,
            activeFacts.length <= 3,
            240,
          )}
        </div>
      ) : (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('knowledge_detail_empty')}</div>
      )}
    </div>
  );

  const renderMemoryTab = () => {
    if (!snapshot) {
      return (
        <div style={panelStyle}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_loading')}</div>
        </div>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '2px' }}>
          <button onClick={() => void loadMemory()} style={pillStyle()}>
            {t('memory_refresh')}
          </button>
          <button onClick={() => void navigator.clipboard.writeText(JSON.stringify(snapshot || {}, null, 2))} style={pillStyle()}>
            {t('memory_copy')}
          </button>
          <button onClick={() => downloadJson('memory-snapshot.json', snapshot || {})} style={pillStyle()}>
            {t('memory_export_json')}
          </button>
          <button onClick={() => setCreating((value) => !value)} style={pillStyle(creating)}>
            {t('memory_new_card')}
          </button>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          <div style={pillStyle()}>{t('memory_count_entities')}: {snapshot.entities?.length || 0}</div>
          <div style={pillStyle()}>{t('memory_count_rules')}: {snapshot.rules?.length || 0}</div>
          <div style={pillStyle()}>{t('memory_count_indexed')}: {snapshot.search_index?.last_indexed_docs || 0}</div>
        </div>

        <input
          value={filter}
          onInput={(event) => setFilter((event.target as HTMLInputElement).value)}
          placeholder={t('memory_filter_placeholder')}
          style={inputStyle}
        />

        {creating ? (
          <div style={{ ...panelStyle, display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={sectionTitleStyle}>{t('memory_new_card')}</div>
            <input value={newName} onInput={(event) => setNewName((event.target as HTMLInputElement).value)} placeholder={t('memory_name')} style={inputStyle} />
            <input value={newType} onInput={(event) => setNewType((event.target as HTMLInputElement).value)} placeholder={t('memory_type')} style={inputStyle} />
            <input value={newKeywords} onInput={(event) => setNewKeywords((event.target as HTMLInputElement).value)} placeholder={t('memory_keywords')} style={inputStyle} />
            <textarea value={newBody} onInput={(event) => setNewBody((event.target as HTMLTextAreaElement).value)} placeholder={t('memory_body')} style={{ ...textareaStyle, minHeight: '100px' }} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => setCreating(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>
                {t('memory_cancel')}
              </button>
              <button onClick={() => void handleCreateEntity()} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>
                {t('memory_create')}
              </button>
            </div>
          </div>
        ) : null}

        <div style={{ display: 'grid', gap: '8px' }}>
          {renderAccordionSection(
            t('memory_search_index'),
            snapshot.search_index?.last_indexed_docs || 0,
            <div style={{ display: 'grid', gap: '8px', fontSize: '11px' }}>
              {([
                [
                  t('memory_search_available'),
                  <span style={{ color: snapshot.search_index?.available ? 'var(--success)' : 'var(--error)' }}>
                    {snapshot.search_index?.available ? t('common_yes') : t('common_no')}
                  </span>,
                ],
                [
                  t('memory_search_db'),
                  <span style={{ color: 'var(--text-primary)' }}>{snapshot.search_index?.db_exists ? t('memory_search_ready') : t('memory_search_empty')}</span>,
                ],
                [
                  t('memory_search_last_op'),
                  <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word', textAlign: 'right' }}>{snapshot.search_index?.last_operation || '—'}</span>,
                ],
                [
                  t('memory_search_indexed'),
                  <span style={{ color: 'var(--text-primary)' }}>{snapshot.search_index?.last_indexed_docs || 0}</span>,
                ],
                [
                  t('memory_search_last_updated'),
                  <span style={{ color: 'var(--text-primary)' }}>{formatTime(snapshot.search_index?.last_updated_ms)}</span>,
                ],
              ] as Array<[string, any]>).map(([label, value]) => (
                <div key={label} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px', paddingBottom: '8px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>{label}</span>
                  <span style={{ minWidth: 0 }}>{value}</span>
                </div>
              ))}
              {snapshot.search_index?.last_error ? (
                <div style={{ color: 'var(--error)', lineHeight: 1.5, wordBreak: 'break-word' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{t('memory_search_last_error')}:</span> {snapshot.search_index.last_error}
                </div>
              ) : null}
            </div>,
            false,
            220,
          )}

          {snapshot.core ? (
            <div style={panelStyle}>
              <div style={{ marginBottom: '8px', display: 'flex', justifyContent: 'space-between', ...sectionTitleStyle }}>
                {t('memory_core')}
                {!editingCore ? (
                  <button
                    onClick={() => {
                      setEditingCore(true);
                      setCoreDraft(snapshot.core || '');
                    }}
                    style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}
                  >
                    {t('memory_edit')}
                  </button>
                ) : null}
              </div>
              {editingCore ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea value={coreDraft} onInput={(event) => setCoreDraft((event.target as HTMLTextAreaElement).value)} style={{ ...textareaStyle, minHeight: '120px' }} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button onClick={() => setEditingCore(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>
                      {t('memory_cancel')}
                    </button>
                    <button onClick={() => void handleSaveCore()} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>
                      {t('memory_save')}
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingCore(true); setCoreDraft(snapshot.core || ''); }}>
                  {snapshot.core}
                </div>
              )}
            </div>
          ) : null}

          <div style={{ ...panelStyle, fontSize: '11px', color: snapshot.today ? 'var(--text-primary)' : 'var(--text-muted)', whiteSpace: 'pre-wrap' }}>
            <div style={{ marginBottom: '8px', ...sectionTitleStyle }}>{t('memory_today')}</div>
            {snapshot.today || t('memory_empty_today')}
          </div>

          {renderAccordionSection(
            t('memory_entities'),
            filteredEntities.length,
            filteredEntities.length > 0 ? filteredEntities.map((entity: MemoryEntityRecord) => (
              <div key={entity.name} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
                <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                  <span>{entity.name}</span>
                  {editingEntity !== entity.name ? (
                    <button onClick={() => { setEditingEntity(entity.name); setEditBody(entity.body || ''); }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>
                      {t('memory_edit')}
                    </button>
                  ) : null}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                  {entity.type ? <span style={pillStyle()}>{entity.type}</span> : null}
                  {typeof entity.access_count === 'number' ? <span style={pillStyle()}>{`access:${entity.access_count}`}</span> : null}
                  {(entity.keywords || []).slice(0, 6).map((item) => <span key={item} style={pillStyle()}>{item}</span>)}
                </div>
                {editingEntity === entity.name ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <textarea value={editBody} onInput={(event) => setEditBody((event.target as HTMLTextAreaElement).value)} style={{ ...textareaStyle, minHeight: '120px' }} />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                      <button onClick={() => setEditingEntity(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '10px' }}>{t('memory_cancel')}</button>
                      <button onClick={() => void handleSaveEntity(entity.name)} style={{ background: 'var(--purple)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '10px', padding: '4px 8px' }}>{t('memory_save')}</button>
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap' }} onDblClick={() => { setEditingEntity(entity.name); setEditBody(entity.body || ''); }}>
                    {entity.body}
                  </div>
                )}
              </div>
            )) : <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_memory')}</div>,
            filteredEntities.length <= 2,
            260,
          )}

          {renderAccordionSection(
            t('memory_rules'),
            filteredRules.length,
            filteredRules.length > 0 ? filteredRules.map((rule, idx) => (
              <div key={`${rule.trigger || 'rule'}-${idx}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', marginBottom: '4px' }}>{rule.trigger || '—'}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', marginBottom: '4px' }}>{rule.lesson || '—'}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{rule.action || '—'}</div>
              </div>
            )) : <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('memory_empty_rules')}</div>,
            filteredRules.length <= 2,
            220,
          )}
        </div>

        {!snapshot.entities?.length && !snapshot.core && !snapshot.today && !snapshot.rules?.length ? (
          <div style={{ ...panelStyle, fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_memory')}</div>
        ) : null}
      </div>
    );
  };

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'sources':
        return renderSourcesTab();
      case 'search':
        return renderSearchTab();
      case 'detail':
        return renderDetailTab();
      case 'memory':
      default:
        return renderMemoryTab();
    }
  };

  return (
    <div style={{ ...panelStyle, padding: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--purple)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px' }}>
            // {t('memory_title')}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={pillStyle(activeTab === 'sources')}>{`${t('knowledge_count_sources')}: ${knowledgeSummary.value?.total || 0}`}</span>
            <span style={pillStyle(activeTab === 'memory')}>{`${t('memory_count_entities')}: ${snapshot?.entities?.length || 0}`}</span>
            <span style={pillStyle(activeTab === 'detail')}>{`${t('knowledge_chunk_count')}: ${activeDoc?.chunk_count || 0}`}</span>
          </div>
        </div>
        <button onClick={() => setPanelExpanded((value) => !value)} style={pillStyle(panelExpanded)}>
          {panelExpanded ? t('memo_collapse') : t('memo_expand')}
        </button>
      </div>

      {panelExpanded ? (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '10px' }}>
            {([
              ['sources', t('memory_tab_sources')],
              ['search', t('memory_tab_search')],
              ['detail', t('memory_tab_detail')],
              ['memory', t('memory_tab_memory')],
            ] as Array<[MemoryPanelTab, string]>).map(([key, label]) => (
              <button key={key} onClick={() => { activeMemoryPanelTab.value = key; }} style={pillStyle(activeTab === key)}>
                {label}
              </button>
            ))}
          </div>
          {saveError || memoryError.value || knowledgeError.value ? (
            <div style={{ fontSize: '11px', color: 'var(--error)', fontFamily: 'var(--font-mono)', marginBottom: '8px', padding: '6px 8px', background: 'rgba(255,68,68,0.1)', borderRadius: '4px' }}>
              {saveError || memoryError.value || knowledgeError.value}
            </div>
          ) : null}
          {renderActiveTab()}
        </>
      ) : null}
    </div>
  );
}
