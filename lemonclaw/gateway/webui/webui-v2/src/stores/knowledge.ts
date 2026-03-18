import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export interface KnowledgeDocumentRecord {
  doc_id: string;
  source_type: string;
  source: string;
  title: string;
  note?: string;
  status?: string;
  created_at_ms?: number;
  updated_at_ms?: number;
  ingested_at_ms?: number;
  chunk_count?: number;
  fact_count?: number;
  last_error?: string;
  metadata?: Record<string, any>;
  refresh_interval_hours?: number;
  next_refresh_at_ms?: number | null;
}

export interface KnowledgeSummary {
  total?: number;
  by_type?: Record<string, number>;
  by_status?: Record<string, number>;
  due_count?: number;
}

export const knowledgeSummary = signal<KnowledgeSummary | null>(null);
export const knowledgeDocuments = signal<KnowledgeDocumentRecord[]>([]);
export const knowledgeError = signal<string | null>(null);
export const knowledgeResults = signal<Array<Record<string, any>>>([]);
export const activeKnowledgeDocument = signal<KnowledgeDocumentRecord | null>(null);
export const activeKnowledgeChunks = signal<Array<Record<string, any>>>([]);
export const activeKnowledgeFacts = signal<Array<Record<string, any>>>([]);
export const selectedKnowledgeSourceType = signal<string>('');
export const selectedKnowledgeResultType = signal<string>('');

export async function loadKnowledge() {
  knowledgeError.value = null;
  try {
    const res = await apiFetch('/api/knowledge');
    const data = await res.json();
    knowledgeSummary.value = data.summary || null;
    knowledgeDocuments.value = data.documents || [];
    if (activeKnowledgeDocument.value) {
      const match = (data.documents || []).find((item: KnowledgeDocumentRecord) => item.doc_id === activeKnowledgeDocument.value?.doc_id);
      if (match) activeKnowledgeDocument.value = match;
    }
  } catch (err: any) {
    console.error('Failed to load knowledge documents', err);
    knowledgeError.value = err?.message || 'Failed to load knowledge';
  }
}

export async function loadKnowledgeDocument(docId: string) {
  knowledgeError.value = null;
  try {
    const res = await apiFetch(`/api/knowledge/documents/${encodeURIComponent(docId)}`);
    const data = await res.json();
    activeKnowledgeDocument.value = data.document || null;
    activeKnowledgeChunks.value = data.chunks || [];
    activeKnowledgeFacts.value = data.facts || [];
  } catch (err: any) {
    console.error('Failed to load knowledge document', err);
    knowledgeError.value = err?.message || 'Failed to load knowledge document';
  }
}

export async function searchKnowledge(query: string, filters?: { source_type?: string; result_type?: string }) {
  knowledgeError.value = null;
  try {
    const q = String(query || '').trim();
    if (!q) {
      knowledgeResults.value = [];
      return;
    }
    if (filters?.source_type !== undefined) selectedKnowledgeSourceType.value = filters.source_type || '';
    if (filters?.result_type !== undefined) selectedKnowledgeResultType.value = filters.result_type || '';
    const params = new URLSearchParams({ q, limit: '8' });
    if (selectedKnowledgeSourceType.value) params.set('source_type', selectedKnowledgeSourceType.value);
    if (selectedKnowledgeResultType.value) params.set('result_type', selectedKnowledgeResultType.value);
    const res = await apiFetch(`/api/knowledge/search?${params.toString()}`);
    const data = await res.json();
    knowledgeResults.value = data.results || [];
  } catch (err: any) {
    console.error('Failed to search knowledge', err);
    knowledgeError.value = err?.message || 'Failed to search knowledge';
  }
}
