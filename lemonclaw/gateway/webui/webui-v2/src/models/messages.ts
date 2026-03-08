export type UIMessageRole = 'user' | 'assistant' | 'system' | 'tool' | 'tool_call';
export type UIMediaKind = 'image' | 'audio' | 'voice' | 'video' | 'pdf' | 'file' | 'document';

export interface UIMedia {
  id: string;
  kind: UIMediaKind;
  path: string;
  url: string;
  filename: string;
  source?: 'history' | 'stream' | 'message_tool';
}

export type UIBlock =
  | { type: 'markdown'; text: string }
  | { type: 'runtime_context'; text: string; collapsed?: boolean }
  | { type: 'transcription'; text: string }
  | { type: 'system_notice'; text: string; kind?: string; level?: 'info' | 'warning' | 'error' }
  | { type: 'media'; mediaId: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool'; state: 'running' | 'done' | 'error'; detail: string; result?: string }
  | { type: 'error'; text: string };

export interface UIMessage {
  id?: string;
  role: UIMessageRole;
  content: string;
  media: UIMedia[];
  blocks: UIBlock[];
  timestamp?: string;
  error?: string;
}

export type ParsedPart =
  | { type: 'markdown'; content: string }
  | { type: 'transcription'; content: string }
  | { type: 'media'; mediaType: string; path: string; label?: string };

let mediaCounter = 0;

export function mediaUrl(path: string): string {
  return `/api/media?path=${encodeURIComponent(path)}`;
}

export function extractRuntimeContext(content: string): { runtime: string | null; body: string } {
  if (!content.startsWith('[Runtime Context')) {
    return { runtime: null, body: content };
  }
  const marker = '\n\n';
  const idx = content.indexOf(marker);
  if (idx === -1) {
    return { runtime: content, body: '' };
  }
  return {
    runtime: content.slice(0, idx).trim(),
    body: content.slice(idx + marker.length).trim(),
  };
}

export function parseStructuredParts(content: string): { runtime: string | null; parts: ParsedPart[] } {
  const { runtime, body } = extractRuntimeContext(content);
  if (!body) return { runtime, parts: [] };

  const tokenRe = /\[(transcription|image|audio|voice|video|pdf|file|document):\s*([^\]]+)\]/gi;
  const parts: ParsedPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  const pushMarkdown = (value: string) => {
    const normalized = value.replace(/^\s+|\s+$/g, '');
    if (normalized) parts.push({ type: 'markdown', content: normalized });
  };

  while ((match = tokenRe.exec(body)) !== null) {
    pushMarkdown(body.slice(lastIndex, match.index));
    const kind = match[1].toLowerCase();
    const payload = match[2].trim();
    if (kind === 'transcription') {
      parts.push({ type: 'transcription', content: payload });
    } else {
      const fileMatch = payload.match(/^(.*?)(?:\s*\(([^()]+)\))?$/);
      const mediaPath = (fileMatch?.[1] || payload).trim();
      const label = fileMatch?.[2]?.trim();
      parts.push({ type: 'media', mediaType: kind, path: mediaPath, label });
    }
    lastIndex = tokenRe.lastIndex;
  }

  pushMarkdown(body.slice(lastIndex));
  return { runtime, parts };
}

function inferMediaKind(path: string, hinted?: string): UIMediaKind {
  const lower = path.toLowerCase();
  if (hinted && ['image', 'audio', 'voice', 'video', 'pdf', 'file', 'document'].includes(hinted)) {
    return hinted as UIMediaKind;
  }
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(lower)) return 'image';
  if (/\.(mp3|wav|m4a|aac|ogg|opus|flac)$/i.test(lower)) return lower.endsWith('.ogg') ? 'voice' : 'audio';
  if (/\.(mp4|webm|mov|mkv|avi)$/i.test(lower)) return 'video';
  if (/\.pdf$/i.test(lower)) return 'pdf';
  return 'file';
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function registerMedia(
  media: UIMedia[],
  byPath: Map<string, string>,
  path: string,
  hinted?: string,
  label?: string,
): string {
  const key = `${hinted || ''}:${path}`;
  const existing = byPath.get(key);
  if (existing) return existing;
  const id = `m${++mediaCounter}`;
  media.push({
    id,
    kind: inferMediaKind(path, hinted),
    path,
    url: mediaUrl(path),
    filename: label || basename(path),
  });
  byPath.set(key, id);
  return id;
}

function buildContentBlocks(content: string, rawMedia: string[] = []): { media: UIMedia[]; blocks: UIBlock[] } {
  const { runtime, parts } = parseStructuredParts(content || '');
  const media: UIMedia[] = [];
  const byPath = new Map<string, string>();
  const blocks: UIBlock[] = [];

  if (runtime) {
    blocks.push({ type: 'runtime_context', text: runtime, collapsed: true });
  }

  for (const part of parts) {
    if (part.type === 'markdown') {
      blocks.push({ type: 'markdown', text: part.content });
    } else if (part.type === 'transcription') {
      blocks.push({ type: 'transcription', text: part.content });
    } else {
      const id = registerMedia(media, byPath, part.path, part.mediaType, part.label);
      blocks.push({ type: 'media', mediaId: id });
    }
  }

  for (const path of rawMedia) {
    const id = registerMedia(media, byPath, path);
    blocks.push({ type: 'media', mediaId: id });
  }

  return { media, blocks };
}

const AUX_BLOCK_TYPES = new Set<UIBlock['type']>(['thinking', 'tool', 'error']);

function auxiliaryBlocks(blocks: UIBlock[]): UIBlock[] {
  return blocks.filter((block) => AUX_BLOCK_TYPES.has(block.type));
}

export function normalizeMessage(raw: any): UIMessage {
  if (Array.isArray(raw?.blocks) && Array.isArray(raw?.media) && raw.media.every((m: any) => typeof m === 'object' && typeof m?.id === 'string')) {
    return raw as UIMessage;
  }
  const role: UIMessageRole = raw?.role || 'assistant';
  const content = typeof raw?.content === 'string' ? raw.content : '';
  const rawMedia: string[] = Array.isArray(raw?.media) ? raw.media.filter((v: unknown) => typeof v === 'string') : [];

  const { media, blocks } = buildContentBlocks(content, rawMedia);
  const out: UIMessage = {
    id: raw?.id,
    role,
    content,
    media,
    blocks: [],
    timestamp: raw?.timestamp,
    error: raw?.error,
  };

  const meta = raw?.metadata && typeof raw.metadata === 'object' ? raw.metadata : {};
  if (typeof meta._ui_notice_text === 'string' && meta._ui_notice_text) {
    out.blocks.push({ type: 'system_notice', text: String(meta._ui_notice_text), kind: meta._ui_notice_kind || 'system', level: meta._ui_notice_level || 'info' });
  }

  if (raw?.thinking) {
    out.blocks.push({ type: 'thinking', text: String(raw.thinking) });
  }

  if (Array.isArray(raw?.tool_calls)) {
    for (const tool of raw.tool_calls) {
      out.blocks.push({
        type: 'tool',
        state: tool?.state || 'done',
        detail: tool?.detail || '',
        result: tool?.result,
      });
    }
  }

  if (role === 'tool_call' && content) {
    out.blocks.push({ type: 'tool', state: 'done', detail: content });
  }

  out.blocks.push(...blocks);

  if (raw?.error) {
    out.blocks.push({ type: 'error', text: String(raw.error) });
  }

  return out;
}

export function withContentAndMedia(message: UIMessage, content: string, rawMedia: string[] = []): UIMessage {
  const { media, blocks } = buildContentBlocks(content, rawMedia);
  return {
    ...message,
    content,
    media,
    blocks: [...auxiliaryBlocks(message.blocks), ...blocks],
  };
}

export function appendThinkingBlock(message: UIMessage, text: string): UIMessage {
  const blocks = [...message.blocks];
  const idx = blocks.findIndex((b) => b.type === 'thinking');
  if (idx >= 0) {
    const existing = blocks[idx] as Extract<UIBlock, { type: 'thinking' }>;
    blocks[idx] = { ...existing, text: existing.text + text };
  } else {
    blocks.unshift({ type: 'thinking', text });
  }
  return { ...message, blocks };
}

export function startToolBlock(message: UIMessage, detail: string): UIMessage {
  return { ...message, blocks: [...message.blocks, { type: 'tool', state: 'running', detail }] };
}

export function resolveLastToolBlock(message: UIMessage, result: string): UIMessage {
  const blocks = [...message.blocks];
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (block.type === 'tool' && block.state === 'running') {
      blocks[i] = { ...block, state: 'done', result };
      return { ...message, blocks };
    }
  }
  return { ...message, blocks: [...blocks, { type: 'tool', state: 'done', detail: 'tool_call', result }] };
}

export function withErrorBlock(message: UIMessage, text: string): UIMessage {
  return { ...message, error: text, blocks: [...message.blocks, { type: 'error', text }] };
}
