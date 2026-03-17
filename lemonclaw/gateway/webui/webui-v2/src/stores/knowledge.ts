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
}

export interface KnowledgeSummary {
  total?: number;
  by_type?: Record<string, number>;
  by_status?: Record<string, number>;
}

export const knowledgeSummary = signal<KnowledgeSummary | null>(null);
export const knowledgeDocuments = signal<KnowledgeDocumentRecord[]>([]);
export const knowledgeError = signal<string | null>(null);
export const knowledgeResults = signal<Array<Record<string, any>>>([]);

export async function loadKnowledge() {
  knowledgeError.value = null;
  try {
    const res = await apiFetch('/api/knowledge');
    const data = await res.json();
    knowledgeSummary.value = data.summary || null;
    knowledgeDocuments.value = data.documents || [];
  } catch (err: any) {
    console.error('Failed to load knowledge documents', err);
    knowledgeError.value = err?.message || 'Failed to load knowledge';
  }
}

export async function searchKnowledge(query: string) {
  knowledgeError.value = null;
  try {
    const q = String(query || '').trim();
    if (!q) {
      knowledgeResults.value = [];
      return;
    }
    const res = await apiFetch(`/api/knowledge/search?q=${encodeURIComponent(q)}&limit=8`);
    const data = await res.json();
    knowledgeResults.value = data.results || [];
  } catch (err: any) {
    console.error('Failed to search knowledge', err);
    knowledgeError.value = err?.message || 'Failed to search knowledge';
  }
}
