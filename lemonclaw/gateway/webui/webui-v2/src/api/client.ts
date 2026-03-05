export class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'APIError';
  }
}

export async function apiFetch(path: string, options: RequestInit & { silent404?: boolean } = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (res.status === 401 && path !== '/api/auth' && path !== '/api/auth/check') {
    window.dispatchEvent(new Event('auth-required'));
  }

  if (!res.ok) {
    if (options.silent404 && res.status === 404) return res;
    let msg = 'API Request Failed';
    try {
      const data = await res.json();
      msg = data.error || msg;
    } catch {}
    throw new APIError(res.status, msg);
  }
  
  return res;
}

export async function* chatStream(params: { message: string, session_key?: string, model?: string, timezone?: string, media?: string[] }, signal?: AbortSignal) {
  const res = await apiFetch('/api/chat/stream', {
    method: 'POST',
    body: JSON.stringify(params),
    signal
  });

  if (!res.body) throw new Error('No readable stream');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6).trim();
          if (!dataStr) continue;
          try {
            const event = JSON.parse(dataStr);
            yield event; 
          } catch (e) {
            console.error('Failed to parse SSE event:', dataStr);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function wsConnect(path: string, onMessage: (data: any) => void, onStatusChange: (connected: boolean) => void) {
  let ws: WebSocket;
  let pingTimer: any;
  let isIntentionallyClosed = false;

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}${path}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      onStatusChange(true);
      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 25000);
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onMessage(data);
      } catch (err) {
        console.error("WS Parse error", err);
      }
    };

    ws.onclose = () => {
      onStatusChange(false);
      clearInterval(pingTimer);
      if (!isIntentionallyClosed) {
        setTimeout(connect, 5000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  };

  connect();

  return {
    close: () => {
      isIntentionallyClosed = true;
      clearInterval(pingTimer);
      if (ws) ws.close();
    }
  };
}