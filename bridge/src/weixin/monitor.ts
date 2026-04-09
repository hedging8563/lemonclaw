import { randomUUID } from 'crypto';

import {
  getUpdates,
  MessageItemType,
  MessageState,
  MessageType,
  sendMessage,
  type GetUpdatesResp,
  type MessageItem,
  type SendMessageReq,
  type WeixinMessage,
} from './api.js';
import {
  DEFAULT_WEIXIN_BASE_URL,
  DEFAULT_WEIXIN_CDN_BASE_URL,
  loadWeixinContextToken,
  listWeixinAccounts,
  loadWeixinAccount,
  normalizeWeixinAccountId,
  saveWeixinContextToken,
  saveWeixinAccount,
  type WeixinAccountRecord,
} from './accounts.js';
import { PersistentWeixinEventQueue } from './event-queue.js';
import { filterWeixinMarkdown } from './markdown-filter.js';
import { extractInboundMediaPaths, sendWeixinMediaFiles } from './media.js';

const DEFAULT_MONITOR_MEDIA_DOWNLOAD_TIMEOUT_MS = 10_000;

export interface WeixinBridgeEvent {
  id: number;
  type: 'message';
  accountId: string;
  senderId: string;
  peerId: string;
  chatId: string;
  content: string;
  timestamp?: number;
  messageId?: number;
  contextToken?: string;
  metadata?: {
    itemTypes: string[];
    hasMedia: boolean;
    mediaPaths?: string[];
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function itemTypeLabel(type: number | undefined): string {
  switch (type) {
    case MessageItemType.TEXT:
      return 'text';
    case MessageItemType.IMAGE:
      return 'image';
    case MessageItemType.VOICE:
      return 'voice';
    case MessageItemType.FILE:
      return 'file';
    case MessageItemType.VIDEO:
      return 'video';
    default:
      return 'unknown';
  }
}

function markerForItems(items: MessageItem[] | undefined): string {
  const firstMedia = items?.find((item) => item.type && item.type !== MessageItemType.TEXT);
  switch (firstMedia?.type) {
    case MessageItemType.IMAGE:
      return '[image]';
    case MessageItemType.VOICE:
      return firstMedia.voice_item?.text?.trim() || '[voice]';
    case MessageItemType.FILE:
      return '[file]';
    case MessageItemType.VIDEO:
      return '[video]';
    default:
      return '';
  }
}

function bodyFromItemList(items: MessageItem[] | undefined): string {
  if (!items?.length) return '';
  for (const item of items) {
    if (item.type === MessageItemType.TEXT && item.text_item?.text != null) {
      const text = String(item.text_item.text).trim();
      if (text) return text;
    }
    if (item.type === MessageItemType.VOICE && item.voice_item?.text) {
      const transcript = String(item.voice_item.text).trim();
      if (transcript) return transcript;
    }
  }
  return markerForItems(items);
}

async function eventFromMessage(
  accountId: string,
  account: WeixinAccountRecord,
  message: WeixinMessage,
): Promise<WeixinBridgeEvent | null> {
  const peerId = String(message.from_user_id || '').trim();
  if (!peerId) return null;
  const normalizedAccountId = normalizeWeixinAccountId(accountId);
  const mediaPaths = await extractInboundMediaPaths({
    accountId: normalizedAccountId,
    message,
    cdnBaseUrl: account.cdnBaseUrl || DEFAULT_WEIXIN_CDN_BASE_URL,
    timeoutMs: DEFAULT_MONITOR_MEDIA_DOWNLOAD_TIMEOUT_MS,
  });
  return {
    id: 0,
    type: 'message',
    accountId: normalizedAccountId,
    senderId: peerId,
    peerId,
    chatId: `${normalizedAccountId}|${peerId}`,
    content: bodyFromItemList(message.item_list),
    timestamp: message.create_time_ms,
    messageId: message.message_id,
    contextToken: message.context_token,
    metadata: {
      itemTypes: (message.item_list || []).map((item) => itemTypeLabel(item.type)),
      hasMedia: Boolean((message.item_list || []).some((item) => item.type && item.type !== MessageItemType.TEXT)),
      mediaPaths,
    },
  };
}

function contextTokenKey(accountId: string, peerId: string): string {
  return `${normalizeWeixinAccountId(accountId)}:${String(peerId || '').trim()}`;
}

export class WeixinMonitorHub {
  private readonly monitors = new Map<string, AbortController>();
  private readonly contextTokens = new Map<string, string>();
  private readonly waiters = new Set<() => void>();
  private readonly eventQueue = new PersistentWeixinEventQueue();

  constructor(private readonly onAccountStatus?: (_account: WeixinAccountRecord | null, _error?: string | null) => void) {}

  private emitEvent(event: Omit<WeixinBridgeEvent, 'id'>): void {
    this.eventQueue.enqueue(event);
    for (const wake of this.waiters) wake();
    this.waiters.clear();
  }

  private async waitForEvents(cursor: number, waitMs: number): Promise<void> {
    if (this.eventQueue.lastId() > cursor) return;
    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        this.waiters.delete(wake);
        resolve();
      }, Math.max(100, waitMs));
      const wake = () => {
        clearTimeout(timeout);
        this.waiters.delete(wake);
        resolve();
      };
      this.waiters.add(wake);
    });
  }

  private async monitorAccountLoop(accountId: string, controller: AbortController): Promise<void> {
    let backoffMs = 2_000;
    while (!controller.signal.aborted) {
      const account = loadWeixinAccount(accountId);
      if (!account?.token) {
        this.onAccountStatus?.(account ?? null, null);
        await sleep(3_000);
        continue;
      }

      try {
        const response = await getUpdates({
          baseUrl: account.baseUrl || DEFAULT_WEIXIN_BASE_URL,
          token: account.token,
          getUpdatesBuf: account.syncBuf || '',
          timeoutMs: 35_000,
        });
        backoffMs = 2_000;
        await this.handleGetUpdatesResponse(account, response);
      } catch (error) {
        const nextError = error instanceof Error ? error.message : String(error);
        saveWeixinAccount(accountId, { lastError: nextError });
        this.onAccountStatus?.(loadWeixinAccount(accountId), nextError);
        await sleep(backoffMs);
        backoffMs = Math.min(backoffMs * 2, 30_000);
      }
    }
  }

  private async handleGetUpdatesResponse(account: WeixinAccountRecord, response: GetUpdatesResp): Promise<void> {
    const accountId = normalizeWeixinAccountId(account.accountId);
    if ((response.ret ?? 0) !== 0 || (response.errcode ?? 0) !== 0) {
      const message = response.errmsg || `ret=${response.ret} errcode=${response.errcode}`;
      saveWeixinAccount(accountId, { lastError: message });
      this.onAccountStatus?.(loadWeixinAccount(accountId), message);
      return;
    }

    const nextSyncBuf = response.get_updates_buf ?? account.syncBuf ?? '';
    if (nextSyncBuf !== (account.syncBuf ?? '')) {
      saveWeixinAccount(accountId, { syncBuf: nextSyncBuf, lastError: '' });
    }

    const messages = response.msgs || [];
    if (messages.length === 0) {
      this.onAccountStatus?.(loadWeixinAccount(accountId) || account, null);
      return;
    }

    const now = Date.now();
    for (const message of messages) {
      const event = await eventFromMessage(accountId, account, message);
      if (!event) continue;
      if (message.context_token && event.peerId) {
        this.contextTokens.set(contextTokenKey(accountId, event.peerId), message.context_token);
        saveWeixinContextToken(accountId, event.peerId, message.context_token);
      }
      this.emitEvent(event);
    }
    saveWeixinAccount(accountId, { lastInboundAt: now, lastError: '', syncBuf: nextSyncBuf });
    this.onAccountStatus?.(loadWeixinAccount(accountId) || account, null);
  }

  ensureMonitors(): void {
    for (const account of listWeixinAccounts()) {
      if (account.token) {
        this.ensureMonitorForAccount(account.accountId);
      }
    }
  }

  ensureMonitorForAccount(accountId: string): void {
    const normalized = normalizeWeixinAccountId(accountId);
    if (!normalized || this.monitors.has(normalized)) return;
    const controller = new AbortController();
    this.monitors.set(normalized, controller);
    void this.monitorAccountLoop(normalized, controller).finally(() => {
      this.monitors.delete(normalized);
    });
  }

  stopMonitor(accountId: string): void {
    const normalized = normalizeWeixinAccountId(accountId);
    const controller = this.monitors.get(normalized);
    if (controller) {
      controller.abort();
      this.monitors.delete(normalized);
    }
  }

  stopAll(): void {
    for (const controller of this.monitors.values()) {
      controller.abort();
    }
    this.monitors.clear();
  }

  async getUpdatesAfter(cursor: number, limit = 50, waitMs = 25_000): Promise<{ events: WeixinBridgeEvent[]; nextCursor: number }> {
    await this.waitForEvents(cursor, waitMs);
    const events = this.eventQueue.listAfter(cursor, Math.max(1, Math.min(limit, 200)));
    const nextCursor = events.length > 0 ? events[events.length - 1].id : cursor;
    return { events, nextCursor };
  }

  ackThrough(cursor: number): void {
    this.eventQueue.ackThrough(cursor);
  }

  async sendText(params: {
    accountId: string;
    to: string;
    text: string;
    contextToken?: string;
    mediaPaths?: string[];
  }): Promise<{ messageId: string }> {
    const accountId = normalizeWeixinAccountId(params.accountId);
    const account = loadWeixinAccount(accountId);
    if (!account?.token) {
      throw new Error('微信账号未连接或 token 不存在。');
    }
    const contextToken = params.contextToken
      || this.contextTokens.get(contextTokenKey(accountId, params.to))
      || loadWeixinContextToken(accountId, params.to);
    if (!contextToken) {
      throw new Error('缺少微信 context token，当前只能回复最近互动过的会话。');
    }
    const filteredText = filterWeixinMarkdown(params.text ?? "");
    const mediaPaths = (params.mediaPaths || []).filter(Boolean);
    if (mediaPaths.length > 0) {
      const result = await sendWeixinMediaFiles({
        accountId,
        to: params.to,
        text: filteredText,
        mediaPaths,
        contextToken,
        baseUrl: account.baseUrl || DEFAULT_WEIXIN_BASE_URL,
        token: account.token,
        cdnBaseUrl: account.cdnBaseUrl || DEFAULT_WEIXIN_CDN_BASE_URL,
      });
      return { messageId: result.messageIds[result.messageIds.length - 1] || '' };
    }

    const clientId = `lemonclaw-weixin-${randomUUID()}`;
    const body: SendMessageReq = {
      msg: {
        from_user_id: '',
        to_user_id: params.to,
        client_id: clientId,
        message_type: MessageType.BOT,
        message_state: MessageState.FINISH,
        context_token: contextToken,
        item_list: filteredText
          ? [{ type: MessageItemType.TEXT, text_item: { text: filteredText } }]
          : undefined,
      },
    };
    await sendMessage({
      baseUrl: account.baseUrl || DEFAULT_WEIXIN_BASE_URL,
      token: account.token,
      body,
    });
    return { messageId: clientId };
  }
}
