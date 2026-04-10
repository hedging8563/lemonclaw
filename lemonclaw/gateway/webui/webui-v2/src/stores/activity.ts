import { signal } from '@preact/signals';
import { apiFetch, wsConnect } from '../api/client';
import { isAuthenticated } from './auth';
import { applyActivityEvent, isStreaming } from './chat';

export interface ActivitySession {
  key: string;
  channel: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export const activitySessions = signal<ActivitySession[]>([]);
export const wsConnected = signal(false);

let wsClient: any = null;

export async function loadActivitySessions() {
  if (!isAuthenticated.value) return;
  try {
    const res = await apiFetch('/api/activity/sessions');
    const data = await res.json();
    activitySessions.value = data.sessions || [];
  } catch (err) {
    console.error("Failed to load activity sessions", err);
  }
}

export function initActivityWS() {
  if (wsClient || !isAuthenticated.value) return;
  wsClient = wsConnect('/ws/activity', (event) => {
    if (!isAuthenticated.value) return;
    if (['message', 'message_in', 'message_out', 'tool_call', 'chunk', 'progress', 'done', 'error'].includes(event.type)) {
      loadActivitySessions();
      if (!isStreaming.value) {
        applyActivityEvent(event);
      }
    }
  }, (connected) => {
    wsConnected.value = connected;
  }, {
    shouldReconnect: () => isAuthenticated.value,
  });
}

export function closeActivityWS() {
  if (wsClient) {
    wsClient.close();
    wsClient = null;
  }
}
