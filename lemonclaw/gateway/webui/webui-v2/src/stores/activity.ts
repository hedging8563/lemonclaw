import { signal } from '@preact/signals';
import { apiFetch, wsConnect } from '../api/client';
import { activeSessionKey } from './sessions';
import { loadHistory, isStreaming } from './chat';

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
  try {
    const res = await apiFetch('/api/activity/sessions');
    const data = await res.json();
    activitySessions.value = data.sessions || [];
  } catch (err) {
    console.error("Failed to load activity sessions", err);
  }
}

export function initActivityWS() {
  if (wsClient) return;
  wsClient = wsConnect('/ws/activity', (event) => {
    if (event.type === 'message_in' || event.type === 'message_out' || event.type === 'tool_call') {
      loadActivitySessions();
      // If we are currently viewing this session and not streaming, reload the history
      if (activeSessionKey.value === event.session_key && !isStreaming.value) {
        loadHistory();
      }
    }
  }, (connected) => {
    wsConnected.value = connected;
  });
}