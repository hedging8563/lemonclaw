import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export interface TriggerRecord {
  trigger_id: string;
  source: string;
  family?: string;
  kind: string;
  status: string;
  payload_summary?: string;
  session_key?: string;
  channel?: string;
  chat_id?: string;
  task_id?: string;
  result_summary?: string;
  error?: string;
  updated_at_ms?: number;
  metadata?: Record<string, any>;
}

export const triggerSummary = signal<Record<string, any> | null>(null);
export const triggers = signal<TriggerRecord[]>([]);
export const triggerPanelError = signal<string | null>(null);

export async function loadTriggers() {
  triggerPanelError.value = null;
  try {
    const res = await apiFetch('/api/triggers?limit=24');
    const data = await res.json();
    triggerSummary.value = data.summary || null;
    triggers.value = data.triggers || [];
  } catch (err: any) {
    console.error('Failed to load triggers', err);
    triggerPanelError.value = err?.message || 'Failed to load triggers';
  }
}
