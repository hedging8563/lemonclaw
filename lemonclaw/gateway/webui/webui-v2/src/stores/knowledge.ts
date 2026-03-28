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
  pinned?: boolean;
  retrieval_count?: number;
  last_hit_at_ms?: number | null;
  last_hit_query?: string;
  last_error?: string;
  metadata?: Record<string, any>;
  archived?: boolean;
  archived_at_ms?: number | null;
  refresh_interval_hours?: number;
  next_refresh_at_ms?: number | null;
}

export interface KnowledgeSummary {
  total?: number;
  by_type?: Record<string, number>;
  by_status?: Record<string, number>;
  due_count?: number;
  pinned_count?: number;
  used_count?: number;
  error_count?: number;
  registered_count?: number;
  ingesting_count?: number;
  archived_count?: number;
}

export type KnowledgeView = 'all' | 'pinned' | 'used' | 'due' | 'ingesting' | 'error' | 'registered' | 'archived';
export type MemoryPanelTab = 'sources' | 'search' | 'detail' | 'memory';
export type KnowledgeSort = 'health' | 'freshness' | 'usage' | 'updated';
export type KnowledgeGovernanceLane = 'attention' | 'freshness' | 'impact' | 'ready';

export interface KnowledgeGovernanceSummary {
  total: number;
  archived: number;
  attention: number;
  freshness: number;
  impact: number;
  ready: number;
  used: number;
  due: number;
  pinned: number;
  error: number;
  registered: number;
  ingesting: number;
}

export interface KnowledgeGovernanceSnapshot {
  summary: KnowledgeGovernanceSummary;
  attention: KnowledgeDocumentRecord[];
  freshness: KnowledgeDocumentRecord[];
  impact: KnowledgeDocumentRecord[];
  ready: KnowledgeDocumentRecord[];
  topRecentlyUsed: KnowledgeDocumentRecord[];
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
export const activeMemoryPanelTab = signal<MemoryPanelTab>('sources');

export function isKnowledgeUsed(doc: KnowledgeDocumentRecord): boolean {
  return Number(doc.retrieval_count || 0) > 0 || Number(doc.last_hit_at_ms || 0) > 0;
}

export function isKnowledgeDue(doc: KnowledgeDocumentRecord, nowMs = Date.now()): boolean {
  const nextRefresh = Number(doc.next_refresh_at_ms || 0);
  return nextRefresh > 0 && nextRefresh <= nowMs;
}

export function filterKnowledgeDocuments(
  docs: KnowledgeDocumentRecord[],
  view: KnowledgeView,
  nowMs = Date.now(),
): KnowledgeDocumentRecord[] {
  const visible = docs.filter((doc) => view === 'archived' ? Boolean(doc.archived) : !doc.archived);
  switch (view) {
    case 'pinned':
      return visible.filter((doc) => Boolean(doc.pinned));
    case 'used':
      return visible.filter((doc) => isKnowledgeUsed(doc));
    case 'due':
      return visible.filter((doc) => isKnowledgeDue(doc, nowMs));
    case 'ingesting':
      return visible.filter((doc) => String(doc.status || '') === 'ingesting');
    case 'error':
      return visible.filter((doc) => String(doc.status || '') === 'error');
    case 'registered':
      return visible.filter((doc) => String(doc.status || '') === 'registered');
    case 'archived':
      return visible;
    default:
      return visible;
  }
}

export function partitionKnowledgeDocuments(
  docs: KnowledgeDocumentRecord[],
  nowMs = Date.now(),
): {
  pinned: KnowledgeDocumentRecord[];
  due: KnowledgeDocumentRecord[];
  used: KnowledgeDocumentRecord[];
  other: KnowledgeDocumentRecord[];
} {
  const seen = new Set<string>();
  const visible = docs.filter((doc) => !doc.archived);
  const pinned: KnowledgeDocumentRecord[] = [];
  const due: KnowledgeDocumentRecord[] = [];
  const used: KnowledgeDocumentRecord[] = [];
  const other: KnowledgeDocumentRecord[] = [];

  for (const doc of visible) {
    if (doc.doc_id && doc.pinned) {
      pinned.push(doc);
      seen.add(doc.doc_id);
    }
  }
  for (const doc of visible) {
    if (!doc.doc_id || seen.has(doc.doc_id)) continue;
    if (isKnowledgeDue(doc, nowMs)) {
      due.push(doc);
      seen.add(doc.doc_id);
    }
  }
  for (const doc of visible) {
    if (!doc.doc_id || seen.has(doc.doc_id)) continue;
    if (isKnowledgeUsed(doc)) {
      used.push(doc);
      seen.add(doc.doc_id);
    }
  }
  for (const doc of visible) {
    if (!doc.doc_id || seen.has(doc.doc_id)) continue;
    other.push(doc);
    seen.add(doc.doc_id);
  }
  return { pinned, due, used, other };
}

export function sortKnowledgeDocuments(
  docs: KnowledgeDocumentRecord[],
  sort: KnowledgeSort,
  nowMs = Date.now(),
): KnowledgeDocumentRecord[] {
  const healthRank = (doc: KnowledgeDocumentRecord) => {
    const status = String(doc.status || '');
    if (doc.archived) return -1;
    if (status === 'error') return 6;
    if (status === 'registered') return 5;
    if (isKnowledgeDue(doc, nowMs)) return 4;
    if (status === 'ingesting') return 3;
    if (doc.pinned) return 2;
    if (isKnowledgeUsed(doc)) return 1;
    return 0;
  };
  return [...docs].sort((a, b) => {
    if (sort === 'usage') {
      const usageA = Number(a.retrieval_count || 0) * 10000000000000 + Number(a.last_hit_at_ms || 0);
      const usageB = Number(b.retrieval_count || 0) * 10000000000000 + Number(b.last_hit_at_ms || 0);
      return usageB - usageA;
    }
    if (sort === 'freshness') {
      const freshnessA = Math.max(Number(a.updated_at_ms || 0), Number(a.ingested_at_ms || 0), Number(a.next_refresh_at_ms || 0));
      const freshnessB = Math.max(Number(b.updated_at_ms || 0), Number(b.ingested_at_ms || 0), Number(b.next_refresh_at_ms || 0));
      return freshnessB - freshnessA;
    }
    if (sort === 'updated') {
      return Number(b.updated_at_ms || 0) - Number(a.updated_at_ms || 0);
    }
    const healthDiff = healthRank(b) - healthRank(a);
    if (healthDiff !== 0) return healthDiff;
    return Number(b.updated_at_ms || 0) - Number(a.updated_at_ms || 0);
  });
}

function compareUsageDocuments(a: KnowledgeDocumentRecord, b: KnowledgeDocumentRecord): number {
  const retrievalA = Number(a.retrieval_count || 0);
  const retrievalB = Number(b.retrieval_count || 0);
  if (retrievalA !== retrievalB) return retrievalB - retrievalA;
  const hitA = Number(a.last_hit_at_ms || 0);
  const hitB = Number(b.last_hit_at_ms || 0);
  if (hitA !== hitB) return hitB - hitA;
  const updatedA = Number(a.updated_at_ms || 0);
  const updatedB = Number(b.updated_at_ms || 0);
  if (updatedA !== updatedB) return updatedB - updatedA;
  return String(a.title || a.source || a.doc_id).localeCompare(String(b.title || b.source || b.doc_id));
}

function compareFreshnessDocuments(a: KnowledgeDocumentRecord, b: KnowledgeDocumentRecord): number {
  const nextRefreshA = Number(a.next_refresh_at_ms || 0);
  const nextRefreshB = Number(b.next_refresh_at_ms || 0);
  if (nextRefreshA !== nextRefreshB) return nextRefreshA - nextRefreshB;
  const updatedA = Number(a.updated_at_ms || 0);
  const updatedB = Number(b.updated_at_ms || 0);
  if (updatedA !== updatedB) return updatedB - updatedA;
  return String(a.title || a.source || a.doc_id).localeCompare(String(b.title || b.source || b.doc_id));
}

function compareAttentionDocuments(a: KnowledgeDocumentRecord, b: KnowledgeDocumentRecord): number {
  const priority = (doc: KnowledgeDocumentRecord) => {
    const status = String(doc.status || '');
    if (status === 'error') return 0;
    if (status === 'registered') return 1;
    if (status === 'ingesting') return 2;
    return 3;
  };
  const priorityDiff = priority(a) - priority(b);
  if (priorityDiff !== 0) return priorityDiff;
  const updatedA = Number(a.updated_at_ms || 0);
  const updatedB = Number(b.updated_at_ms || 0);
  if (updatedA !== updatedB) return updatedB - updatedA;
  return String(a.title || a.source || a.doc_id).localeCompare(String(b.title || b.source || b.doc_id));
}

function isKnowledgeFreshSoon(doc: KnowledgeDocumentRecord, nowMs: number, windowMs: number): boolean {
  const nextRefresh = Number(doc.next_refresh_at_ms || 0);
  if (nextRefresh <= 0) return false;
  if (nextRefresh <= nowMs) return true;
  return nextRefresh <= nowMs + Math.max(0, windowMs);
}

export function buildKnowledgeGovernanceSnapshot(
  docs: KnowledgeDocumentRecord[],
  nowMs = Date.now(),
  freshnessWindowMs = 24 * 60 * 60 * 1000,
  recentUsageLimit = 5,
): KnowledgeGovernanceSnapshot {
  const visible = docs.filter((doc) => !doc.archived);
  const archived = docs.filter((doc) => Boolean(doc.archived)).length;
  const attention = visible.filter((doc) => {
    const status = String(doc.status || '');
    return status === 'error' || status === 'registered' || status === 'ingesting';
  }).sort(compareAttentionDocuments);
  const freshness = visible.filter((doc) => {
    if (attention.some((item) => item.doc_id === doc.doc_id)) return false;
    return isKnowledgeFreshSoon(doc, nowMs, freshnessWindowMs);
  }).sort(compareFreshnessDocuments);
  const impact = visible.filter((doc) => {
    if (attention.some((item) => item.doc_id === doc.doc_id)) return false;
    if (freshness.some((item) => item.doc_id === doc.doc_id)) return false;
    return isKnowledgeUsed(doc);
  }).sort(compareUsageDocuments);
  const ready = visible.filter((doc) => {
    if (attention.some((item) => item.doc_id === doc.doc_id)) return false;
    if (freshness.some((item) => item.doc_id === doc.doc_id)) return false;
    if (impact.some((item) => item.doc_id === doc.doc_id)) return false;
    return true;
  }).sort((a, b) => Number(b.updated_at_ms || 0) - Number(a.updated_at_ms || 0));
  const topRecentlyUsed = [...visible]
    .filter((doc) => isKnowledgeUsed(doc))
    .sort(compareUsageDocuments)
    .slice(0, Math.max(0, recentUsageLimit));

  return {
    summary: {
      total: visible.length,
      archived,
      attention: attention.length,
      freshness: freshness.length,
      impact: impact.length,
      ready: ready.length,
      used: visible.filter((doc) => isKnowledgeUsed(doc)).length,
      due: visible.filter((doc) => isKnowledgeDue(doc, nowMs)).length,
      pinned: visible.filter((doc) => Boolean(doc.pinned)).length,
      error: visible.filter((doc) => String(doc.status || '') === 'error').length,
      registered: visible.filter((doc) => String(doc.status || '') === 'registered').length,
      ingesting: visible.filter((doc) => String(doc.status || '') === 'ingesting').length,
    },
    attention,
    freshness,
    impact,
    ready,
    topRecentlyUsed,
  };
}

export async function loadKnowledge() {
  knowledgeError.value = null;
  try {
    const res = await apiFetch('/api/knowledge?include_archived=1');
    const data = await res.json();
    knowledgeSummary.value = data.summary || null;
    knowledgeDocuments.value = data.documents || [];
    if (activeKnowledgeDocument.value) {
      const match = (data.documents || []).find((item: KnowledgeDocumentRecord) => item.doc_id === activeKnowledgeDocument.value?.doc_id);
      if (match) {
        activeKnowledgeDocument.value = match;
      } else {
        activeKnowledgeDocument.value = null;
        activeKnowledgeChunks.value = [];
        activeKnowledgeFacts.value = [];
      }
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
