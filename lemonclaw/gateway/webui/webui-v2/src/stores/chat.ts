import { signal } from '@preact/signals';
import { chatStream, apiFetch } from '../api/client';
import { activeSessionKey, loadSessions } from './sessions';
import { loadConductor } from './conductor';
import { currentModel } from './models';
import { appendThinkingBlock, normalizeMessage, resolveLastToolBlock, startToolBlock, withContentAndMedia, withErrorBlock } from '../models/messages';
import type { UIMessage } from '../models/messages';

export type ChatMessage = UIMessage;

export const messages = signal<ChatMessage[]>([]);
export const isStreaming = signal(false);
export const streamError = signal<string | null>(null);
export const attachments = signal<{ path: string, filename: string, url?: string }[]>([]);
export const inputText = signal('');
export const isLoadingHistory = signal(false);
export const hasMoreHistory = signal(false);
export const isLoadingMore = signal(false);

let currentAbortController: AbortController | null = null;
let _nextBefore: number | null = null;

export function abortStream() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
}

export async function uploadFile(file: File) {
  const reader = new FileReader();
  reader.onload = async (e) => {
    const base64 = e.target?.result as string;
    try {
      const res = await apiFetch('/api/chat/upload', {
        method: 'POST',
        body: JSON.stringify({ data: base64, filename: file.name })
      });
      const data = await res.json();
      attachments.value = [...attachments.value, { path: data.path, filename: file.name, url: base64 }];
    } catch (err) {
      console.error('Upload failed', err);
    }
  };
  reader.readAsDataURL(file);
}

export async function loadHistory() {
  if (!activeSessionKey.value) return;

  messages.value = [];
  inputText.value = '';
  attachments.value = [];
  isLoadingHistory.value = true;
  hasMoreHistory.value = false;
  _nextBefore = null;

  try {
    let url = `/api/sessions/${encodeURIComponent(activeSessionKey.value)}/messages`;
    if (!activeSessionKey.value.startsWith('webui:')) {
      url = `/api/activity/messages?session_key=${encodeURIComponent(activeSessionKey.value)}&limit=50`;
    }

    const res = await apiFetch(url, { silent404: true });
    if (res.status === 404 || res.status === 403) return;

    const data = await res.json();
    messages.value = (data.messages || []).map((msg: any) => normalizeMessage(msg));
    hasMoreHistory.value = !!data.has_more;
    _nextBefore = data.next_before ?? null;
  } catch (err) {
    console.error('Failed to load history', err);
  } finally {
    isLoadingHistory.value = false;
  }
}

export async function loadMoreHistory() {
  if (isLoadingMore.value || !hasMoreHistory.value || _nextBefore == null || !activeSessionKey.value) return;
  if (activeSessionKey.value.startsWith('webui:')) return;

  isLoadingMore.value = true;
  try {
    const url = `/api/activity/messages?session_key=${encodeURIComponent(activeSessionKey.value)}&limit=50&before=${_nextBefore}`;
    const res = await apiFetch(url, { silent404: true });
    if (res.status === 404 || res.status === 403) return;

    const data = await res.json();
    const older = (data.messages || []).map((msg: any) => normalizeMessage(msg));
    messages.value = [...older, ...messages.value];
    hasMoreHistory.value = !!data.has_more;
    _nextBefore = data.next_before ?? null;
  } catch (err) {
    console.error('Failed to load more history', err);
  } finally {
    isLoadingMore.value = false;
  }
}

export async function sendMessage(content: string) {
  if (isStreaming.value) return;

  const mediaPaths = attachments.value.map(a => a.path);
  attachments.value = [];

  const userMsg: ChatMessage = normalizeMessage({ role: 'user', content, media: mediaPaths });
  messages.value = [...messages.value, userMsg];
  isStreaming.value = true;
  streamError.value = null;

  const assistantMsg: ChatMessage = normalizeMessage({ role: 'assistant', content: '' });
  messages.value = [...messages.value, assistantMsg];

  currentAbortController = new AbortController();
  try {
    const stream = chatStream({
      message: content,
      session_key: activeSessionKey.value,
      model: currentModel.value || undefined,
      media: mediaPaths.length > 0 ? mediaPaths : undefined,
    }, currentAbortController.signal);

    for await (const event of stream) {
      const currentMessages = [...messages.value];
      const lastIdx = currentMessages.length - 1;
      const lastMsg = { ...currentMessages[lastIdx] };

      if (event.type === 'content') {
        Object.assign(lastMsg, withContentAndMedia(lastMsg, lastMsg.content + event.data, lastMsg.media.map((m) => m.path)));
      } else if (event.type === 'thinking') {
        Object.assign(lastMsg, appendThinkingBlock(lastMsg, event.data));
      } else if (event.type === 'tool_start') {
        Object.assign(lastMsg, startToolBlock(lastMsg, event.data));
      } else if (event.type === 'tool_result') {
        Object.assign(lastMsg, resolveLastToolBlock(lastMsg, event.data));
      } else if (event.type === 'outbound') {
        const payload = normalizeMessage(event.data || {});
        if (!lastMsg.content && lastMsg.media.length === 0 && lastMsg.role === 'assistant') {
          Object.assign(lastMsg, payload);
          currentMessages[lastIdx] = lastMsg;
        } else {
          currentMessages.push(payload);
        }
      } else if (event.type === 'done') {
        if (event.data) {
          const payload = normalizeMessage(event.data);
          Object.assign(lastMsg, { ...payload, blocks: [...lastMsg.blocks.filter((b) => ['thinking', 'tool', 'error'].includes(b.type)), ...payload.blocks.filter((b) => !['thinking', 'tool', 'error'].includes(b.type))] });
        }
      } else if (event.type === 'error') {
        Object.assign(lastMsg, withErrorBlock(lastMsg, event.data));
      }

      currentMessages[lastIdx] = lastMsg;
      messages.value = currentMessages;
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      console.log('Stream aborted by user');
    } else {
      console.error('Stream error', err);
      streamError.value = err.message || 'Connection failed';
    }
  } finally {
    currentAbortController = null;
    isStreaming.value = false;
    loadSessions();
    loadConductor();
  }
}
