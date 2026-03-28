import { describe, expect, it } from 'vitest';
import {
  buildKnowledgeGovernanceSnapshot,
  filterKnowledgeDocuments,
  isKnowledgeDue,
  isKnowledgeUsed,
  partitionKnowledgeDocuments,
  type KnowledgeDocumentRecord,
} from '../src/stores/knowledge';

const NOW = 1_800_000_000_000;

function doc(id: string, patch: Partial<KnowledgeDocumentRecord> = {}): KnowledgeDocumentRecord {
  return {
    doc_id: id,
    source_type: 'manual',
    source: `manual://${id}`,
    title: id,
    ...patch,
  };
}

describe('knowledge helpers', () => {
  it('detects used and due documents', () => {
    expect(isKnowledgeUsed(doc('plain'))).toBe(false);
    expect(isKnowledgeUsed(doc('used', { retrieval_count: 2 }))).toBe(true);
    expect(isKnowledgeDue(doc('due', { next_refresh_at_ms: NOW - 1 }), NOW)).toBe(true);
    expect(isKnowledgeDue(doc('future', { next_refresh_at_ms: NOW + 1000 }), NOW)).toBe(false);
  });

  it('filters documents by quick view', () => {
    const docs = [
      doc('pinned', { pinned: true }),
      doc('used', { retrieval_count: 1 }),
      doc('due', { next_refresh_at_ms: NOW - 1 }),
      doc('ingesting', { status: 'ingesting' }),
    ];
    expect(filterKnowledgeDocuments(docs, 'pinned', NOW).map((item) => item.doc_id)).toEqual(['pinned']);
    expect(filterKnowledgeDocuments(docs, 'used', NOW).map((item) => item.doc_id)).toEqual(['used']);
    expect(filterKnowledgeDocuments(docs, 'due', NOW).map((item) => item.doc_id)).toEqual(['due']);
    expect(filterKnowledgeDocuments(docs, 'ingesting', NOW).map((item) => item.doc_id)).toEqual(['ingesting']);
  });

  it('partitions documents without duplication', () => {
    const docs = [
      doc('pinned', { pinned: true, retrieval_count: 4 }),
      doc('due', { next_refresh_at_ms: NOW - 1 }),
      doc('used', { retrieval_count: 1 }),
      doc('other'),
    ];
    const groups = partitionKnowledgeDocuments(docs, NOW);
    expect(groups.pinned.map((item) => item.doc_id)).toEqual(['pinned']);
    expect(groups.due.map((item) => item.doc_id)).toEqual(['due']);
    expect(groups.used.map((item) => item.doc_id)).toEqual(['used']);
    expect(groups.other.map((item) => item.doc_id)).toEqual(['other']);
  });

  it('builds a governance snapshot with attention, freshness, impact and ready lanes', () => {
    const docs = [
      doc('error', { status: 'error', last_error: 'broken sync' }),
      doc('registered', { status: 'registered' }),
      doc('ingesting', { status: 'ingesting' }),
      doc('due', { next_refresh_at_ms: NOW - 1 }),
      doc('soon', { next_refresh_at_ms: NOW + 10_000 }),
      doc('used-a', { retrieval_count: 2, last_hit_at_ms: NOW - 10 }),
      doc('used-b', { retrieval_count: 2, last_hit_at_ms: NOW - 100 }),
      doc('ready'),
      doc('archived', { archived: true, retrieval_count: 99, next_refresh_at_ms: NOW - 1 }),
    ];

    const snapshot = buildKnowledgeGovernanceSnapshot(docs, NOW, 60_000, 2);

    expect(snapshot.summary.total).toBe(8);
    expect(snapshot.summary.archived).toBe(1);
    expect(snapshot.summary.attention).toBe(3);
    expect(snapshot.summary.freshness).toBe(2);
    expect(snapshot.summary.impact).toBe(2);
    expect(snapshot.summary.ready).toBe(1);
    expect(snapshot.summary.used).toBe(2);
    expect(snapshot.summary.due).toBe(1);
    expect(snapshot.summary.pinned).toBe(0);
    expect(snapshot.attention.map((item) => item.doc_id)).toEqual(['error', 'registered', 'ingesting']);
    expect(snapshot.freshness.map((item) => item.doc_id)).toEqual(['due', 'soon']);
    expect(snapshot.impact.map((item) => item.doc_id)).toEqual(['used-a', 'used-b']);
    expect(snapshot.ready.map((item) => item.doc_id)).toEqual(['ready']);
    expect(snapshot.topRecentlyUsed.map((item) => item.doc_id)).toEqual(['used-a', 'used-b']);
  });
});
