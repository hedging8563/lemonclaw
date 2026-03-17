import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export interface MemoryEntityRecord {
  name: string;
  type?: string;
  keywords?: string[];
  access_count?: number;
  body?: string;
}

export interface MemoryRuleRecord {
  trigger?: string;
  lesson?: string;
  action?: string;
}

export interface MemorySearchStatus {
  available?: boolean;
  db_path?: string;
  db_exists?: boolean;
  last_operation?: string;
  last_error?: string;
  last_updated_ms?: number;
  last_indexed_docs?: number;
}

export interface MemorySnapshot {
  core?: string;
  long_term?: string;
  today?: string;
  history?: string[];
  entities?: MemoryEntityRecord[];
  rules?: MemoryRuleRecord[];
  search_index?: MemorySearchStatus;
}

export const memory = signal<MemorySnapshot | null>(null);
export const memoryError = signal<string | null>(null);

export async function loadMemory() {
  memoryError.value = null;
  try {
    const res = await apiFetch('/api/memory');
    const data = await res.json();
    memory.value = data;
  } catch (err: any) {
    console.error("Failed to load memory data", err);
    memoryError.value = err?.message || 'Failed to load memory';
  }
}
