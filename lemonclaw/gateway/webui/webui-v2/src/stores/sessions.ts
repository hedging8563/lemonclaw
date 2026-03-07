import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export interface Session {
  key: string;
  title: string;
  updated_at: string;
  message_count: number;
  model: string;
}

export const sessions = signal<Session[]>([]);
export const activeSessionKey = signal<string>('webui:default');

export async function loadSessions() {
  try {
    const res = await apiFetch('/api/sessions');
    const data = await res.json();
    sessions.value = data.sessions || [];
  } catch (err) {
    console.error("Failed to load sessions", err);
  }
}

export async function deleteSession(key: string) {
  await apiFetch(`/api/sessions/${encodeURIComponent(key)}`, { method: 'DELETE' });
  if (activeSessionKey.value === key) {
    activeSessionKey.value = 'webui:default';
  }
  await loadSessions();
}