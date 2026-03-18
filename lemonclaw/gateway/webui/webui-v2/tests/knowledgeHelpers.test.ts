import { describe, expect, it } from 'vitest';
import { filterKnowledgeDocuments, isKnowledgeDue, isKnowledgeUsed, partitionKnowledgeDocuments, type KnowledgeDocumentRecord } from '../src/stores/knowledge';

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
});
