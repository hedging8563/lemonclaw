import { signal } from '@preact/signals';
import { chatStream, apiFetch, wsConnect } from '../api/client';
import { isAuthenticated } from './auth';
import { activeSessionKey, loadSessions } from './sessions';
import { loadConductor } from './conductor';
import { currentModel } from './models';
import { appendThinkingBlock, normalizeMessage, resolveLastToolBlock, startToolBlock, withContentAndMedia, withErrorBlock } from '../models/messages';
import type { UIMessage } from '../models/messages';

export type ChatMessage = UIMessage;
export type AttachmentStatus = 'uploading' | 'ready' | 'failed';
export type AttachmentKind = 'image' | 'video' | 'audio' | 'document';

export interface AttachmentItem {
  id: string;
  path?: string;
  filename: string;
  url?: string;
  status: AttachmentStatus;
  kind: AttachmentKind;
  error?: string;
  file?: File;
}

export const messages = signal<ChatMessage[]>([]);
export const isStreaming = signal(false);
export const streamError = signal<string | null>(null);
export const attachments = signal<AttachmentItem[]>([]);
export const inputText = signal('');
export const isLoadingHistory = signal(false);
export const hasMoreHistory = signal(false);
export const isLoadingMore = signal(false);

const ACTIVITY_STREAM_ID_PREFIX = 'activity-stream:';

function activityStreamMessageId(sessionKey: string): string {
  return `${ACTIVITY_STREAM_ID_PREFIX}${sessionKey}`;
}

function upsertActivityStreamMessage(content: string, timestamp?: string) {
  const sessionKey = activeSessionKey.value;
  if (!sessionKey) return;
  const streamId = activityStreamMessageId(sessionKey);
  const payload = normalizeMessage({ id: streamId, role: 'assistant', content, timestamp });
  const current = [...messages.value];
  const index = current.findIndex((msg) => msg.id === streamId);
  if (index >= 0) {
    current[index] = payload;
  } else {
    current.push(payload);
  }
  messages.value = current;
}

function upsertActivityErrorMessage(content: string, timestamp?: string) {
  const sessionKey = activeSessionKey.value;
  if (!sessionKey) return;
  const streamId = activityStreamMessageId(sessionKey);
  const payload = normalizeMessage({ id: streamId, role: 'assistant', content: '', timestamp, error: content });
  const current = [...messages.value];
  const index = current.findIndex((msg) => msg.id === streamId);
  if (index >= 0) {
    current[index] = payload;
  } else {
    current.push(payload);
  }
  messages.value = current;
}

export function applyActivityEvent(event: any) {
  if (!isAuthenticated.value) return;
  const sessionKey = activeSessionKey.value;
  if (!sessionKey || sessionKey.startsWith('webui:') || isStreaming.value) return;
  if (event.session_key !== sessionKey) return;

  if (event.type === 'chunk' || event.type === 'progress') {
    upsertActivityStreamMessage(String(event.content || ''), event.timestamp);
    return;
  }

  if (event.type === 'done') {
    void loadHistory();
    return;
  }

  if (event.type === 'error') {
    upsertActivityErrorMessage(String(event.content || 'Activity stream failed'), event.timestamp);
    return;
  }
}

let currentAbortController: AbortController | null = null;
let _nextBefore: number | null = null;
let sessionWsClient: any = null;
let sessionWsKey: string | null = null;

function historyMessageKey(msg: ChatMessage): string {
  const media = msg.media.map((m) => `${m.kind}:${m.path}`).join('|');
  const blocks = msg.blocks.map((b) => `${b.type}:${JSON.stringify(b)}`).join('|');
  return `${msg.id || ''}::${msg.role}::${msg.timestamp || ''}::${msg.content}::${media}::${blocks}`;
}


function mergeSessionMessages(incoming: ChatMessage[]) {
  const seen = new Set(messages.value.map(historyMessageKey));
  const appended = incoming.filter((msg) => !seen.has(historyMessageKey(msg)));
  if (appended.length > 0) {
    messages.value = [...messages.value, ...appended];
  }
}

export function syncSessionStream() {
  const key = activeSessionKey.value;
  if (!isAuthenticated.value) {
    closeSessionStream();
    return;
  }
  if (sessionWsKey === key) return;

  if (sessionWsClient) {
    sessionWsClient.close();
    sessionWsClient = null;
    sessionWsKey = null;
  }

  if (!key || key.startsWith('webui:')) return;

  const params = new URLSearchParams({
    session_key: key,
    known_count: String(messages.value.length),
  });
  sessionWsClient = wsConnect(`/ws/session?${params.toString()}`, (event) => {
    if (event.type === 'messages' && event.session_key === activeSessionKey.value && !isStreaming.value) {
      mergeSessionMessages((event.messages || []).map((msg: any) => normalizeMessage(msg)));
    }
  }, () => {}, {
    shouldReconnect: () => isAuthenticated.value,
  });
  sessionWsKey = key;
}

export function closeSessionStream() {
  if (sessionWsClient) {
    sessionWsClient.close();
    sessionWsClient = null;
    sessionWsKey = null;
  }
}

export function abortStream() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
}

function attachmentId() {
  return `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function guessAttachmentKind(file: File): AttachmentKind {
  const type = String(file.type || '').toLowerCase();
  const name = file.name.toLowerCase();
  if (type.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/.test(name)) return 'image';
  if (type.startsWith('video/') || /\.(mp4|mov|webm|m4v)$/.test(name)) return 'video';
  if (type.startsWith('audio/') || /\.(mp3|wav|ogg|m4a|aac)$/.test(name)) return 'audio';
  return 'document';
}

function updateAttachment(id: string, updater: (current: AttachmentItem) => AttachmentItem) {
  attachments.value = attachments.value.map((item) => item.id === id ? updater(item) : item);
}

async function uploadAttachmentData(id: string, dataUrl: string) {
  updateAttachment(id, (item) => ({ ...item, status: 'uploading', error: undefined, url: dataUrl }));
  const item = attachments.value.find((entry) => entry.id === id);
  if (!item) return;
  try {
    const res = await apiFetch('/api/chat/upload', {
      method: 'POST',
      body: JSON.stringify({ data: dataUrl, filename: item.filename }),
    });
    const data = await res.json();
    updateAttachment(id, (current) => ({ ...current, path: data.path, status: 'ready', error: undefined, url: dataUrl }));
  } catch (err: any) {
    console.error('Upload failed', err);
    updateAttachment(id, (current) => ({ ...current, status: 'failed', error: err?.message || 'Upload failed', url: dataUrl }));
  }
}

export async function uploadFile(file: File) {
  const id = attachmentId();
  attachments.value = [...attachments.value, {
    id,
    filename: file.name,
    kind: guessAttachmentKind(file),
    status: 'uploading',
    file,
  }];
  const reader = new FileReader();
  reader.onload = async (event) => {
    const base64 = event.target?.result as string;
    if (!base64) {
      updateAttachment(id, (current) => ({ ...current, status: 'failed', error: 'Upload failed' }));
      return;
    }
    await uploadAttachmentData(id, base64);
  };
  reader.onerror = () => {
    updateAttachment(id, (current) => ({ ...current, status: 'failed', error: 'Upload failed' }));
  };
  reader.readAsDataURL(file);
}

export async function retryUploadAttachment(id: string) {
  const item = attachments.value.find((entry) => entry.id === id);
  if (!item) return;
  if (item.url) {
    await uploadAttachmentData(id, item.url);
    return;
  }
  if (!item.file) return;
  const reader = new FileReader();
  reader.onload = async (event) => {
    const base64 = event.target?.result as string;
    if (!base64) {
      updateAttachment(id, (current) => ({ ...current, status: 'failed', error: 'Upload failed' }));
      return;
    }
    await uploadAttachmentData(id, base64);
  };
  reader.onerror = () => {
    updateAttachment(id, (current) => ({ ...current, status: 'failed', error: 'Upload failed' }));
  };
  reader.readAsDataURL(item.file);
}

export async function loadHistory() {
  if (!activeSessionKey.value || !isAuthenticated.value) return;

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
  if (isLoadingMore.value || !hasMoreHistory.value || _nextBefore == null || !activeSessionKey.value || !isAuthenticated.value) return;
  if (activeSessionKey.value.startsWith('webui:')) return;

  isLoadingMore.value = true;
  try {
    const url = `/api/activity/messages?session_key=${encodeURIComponent(activeSessionKey.value)}&limit=50&before=${_nextBefore}`;
    const res = await apiFetch(url, { silent404: true });
    if (res.status === 404 || res.status === 403) return;

    const data = await res.json();
    const older = (data.messages || []).map((msg: any) => normalizeMessage(msg));
    const seen = new Set(messages.value.map(historyMessageKey));
    const merged = [...older.filter((msg: ChatMessage) => !seen.has(historyMessageKey(msg))), ...messages.value];
    messages.value = merged;
    hasMoreHistory.value = !!data.has_more;
    _nextBefore = data.next_before ?? null;
  } catch (err) {
    console.error('Failed to load more history', err);
  } finally {
    isLoadingMore.value = false;
  }
}

export async function sendMessage(content: string) {
  if (isStreaming.value || !isAuthenticated.value) return;

  const mediaPaths = attachments.value.filter((item) => item.status === 'ready' && item.path).map((item) => item.path!) ;
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
          Object.assign(lastMsg, mergeOutboundPayload(lastMsg, payload));
          currentMessages[lastIdx] = lastMsg;
        } else {
          currentMessages.push(payload);
        }
      } else if (event.type === 'done') {
        if (event.data) {
          const payload = mergeDonePayload(lastMsg, event.data);
          Object.assign(lastMsg, payload);
        }
        if (event.session_key && event.session_key !== activeSessionKey.value) {
          activeSessionKey.value = event.session_key;
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
      const currentMessages = [...messages.value];
      const lastIdx = currentMessages.length - 1;
      if (lastIdx >= 0) {
        const lastMsg = { ...currentMessages[lastIdx] };
        const errorMessage = err.status === 409 && err.message
          ? err.message
          : (err.message || 'Connection failed');
        Object.assign(lastMsg, withErrorBlock(lastMsg, errorMessage));
        currentMessages[lastIdx] = lastMsg;
        messages.value = currentMessages;
      }
      streamError.value = err.message || 'Connection failed';
    }
  } finally {
    currentAbortController = null;
    isStreaming.value = false;
    loadSessions();
    loadConductor();
  }
}

const AUX_BLOCK_TYPES = new Set<ChatMessage['blocks'][number]['type']>(['thinking', 'tool', 'error']);

export function mergeOutboundPayload(lastMsg: ChatMessage, raw: any): ChatMessage {
  const payload = normalizeMessage(raw || {});
  return {
    ...lastMsg,
    ...payload,
    blocks: [
      ...lastMsg.blocks.filter((block) => AUX_BLOCK_TYPES.has(block.type as any)),
      ...payload.blocks.filter((block) => !AUX_BLOCK_TYPES.has(block.type as any)),
    ],
  };
}

export function mergeDonePayload(lastMsg: ChatMessage, raw: any): ChatMessage {
  const payload = normalizeMessage(raw || {});
  const hasVisibleContent = Boolean(payload.content || payload.media.length > 0 || payload.error || payload.blocks.length > 0);
  if (!hasVisibleContent) return lastMsg;
  return {
    ...lastMsg,
    ...payload,
    blocks: [
      ...lastMsg.blocks.filter((block) => AUX_BLOCK_TYPES.has(block.type as any)),
      ...payload.blocks.filter((block) => !AUX_BLOCK_TYPES.has(block.type as any)),
    ],
  };
}
