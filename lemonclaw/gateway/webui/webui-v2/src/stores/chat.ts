import { signal } from '@preact/signals';
import { chatStream, apiFetch } from '../api/client';
import { activeSessionKey, loadSessions } from './sessions';
import { loadConductor } from './conductor';
import { currentModel } from './models';

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  thinking?: string;
  tool_calls?: any[];
  error?: string;
}

export const messages = signal<ChatMessage[]>([]);
export const isStreaming = signal(false);
export const streamError = signal<string | null>(null);
export const attachments = signal<{ path: string, filename: string, url?: string }[]>([]);
export const inputText = signal('');
export const isLoadingHistory = signal(false);

let currentAbortController: AbortController | null = null;

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
      console.error("Upload failed", err);
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
  
  try {
    let url = `/api/sessions/${activeSessionKey.value}/messages`;
    if (!activeSessionKey.value.startsWith('webui:')) {
      url = `/api/activity/messages?session_key=${encodeURIComponent(activeSessionKey.value)}&limit=100`;
    }

    const res = await apiFetch(url, { silent404: true });
    if (res.status === 404 || res.status === 403) return; 
    
    const data = await res.json();
    messages.value = data.messages || [];
  } catch (err) {
    console.error("Failed to load history", err);
  } finally {
    isLoadingHistory.value = false;
  }
}

export async function sendMessage(content: string) {
  if (isStreaming.value) return;
  
  const mediaPaths = attachments.value.map(a => a.path);
  attachments.value = []; // Clear attachments UI instantly

  const userMsg: ChatMessage = { role: 'user', content };
  messages.value = [...messages.value, userMsg];
  isStreaming.value = true;
  streamError.value = null;

  const assistantMsg: ChatMessage = { role: 'assistant', content: '', thinking: '', tool_calls: [] };
  messages.value = [...messages.value, assistantMsg];

  currentAbortController = new AbortController();
  try {
    const stream = chatStream({
      message: content,
      session_key: activeSessionKey.value,
      model: currentModel.value || undefined,
      media: mediaPaths.length > 0 ? mediaPaths : undefined
    }, currentAbortController.signal);

    for await (const event of stream) {
      const currentMessages = [...messages.value];
      const lastIdx = currentMessages.length - 1;
      const lastMsg = { ...currentMessages[lastIdx] };

      if (event.type === 'content') {
        lastMsg.content += event.data;
      } else if (event.type === 'thinking') {
        lastMsg.thinking = (lastMsg.thinking || '') + event.data;
      } else if (event.type === 'tool_start') {
        lastMsg.tool_calls = lastMsg.tool_calls || [];
        lastMsg.tool_calls.push({ state: 'running', detail: event.data });
      } else if (event.type === 'tool_result') {
         if (lastMsg.tool_calls && lastMsg.tool_calls.length > 0) {
            lastMsg.tool_calls[lastMsg.tool_calls.length - 1].state = 'done';
            lastMsg.tool_calls[lastMsg.tool_calls.length - 1].result = event.data;
         }
      } else if (event.type === 'error') {
        lastMsg.error = event.data;
      }
      
      currentMessages[lastIdx] = lastMsg;
      messages.value = currentMessages;
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      console.log('Stream aborted by user');
    } else {
      console.error("Stream error", err);
      streamError.value = err.message || "Connection failed";
    }
  } finally {
    currentAbortController = null;
    isStreaming.value = false;
    loadSessions(); 
    loadConductor();
  }
}