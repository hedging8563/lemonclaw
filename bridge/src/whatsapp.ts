/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { mkdir, writeFile } from 'fs/promises';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { basename, extname, join } from 'path';
import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

const VERSION = '0.1.0';

export interface InboundMessage {
  id: string;
  sender: string;
  pn: string;
  content: string;
  timestamp: number;
  isGroup: boolean;
  mentions?: string[];
  quotedParticipant?: string;
  media?: string[];
  mediaToken?: string;
}

export interface WhatsAppAccountSummary {
  id?: string;
  phone?: string;
  name?: string;
}

export interface WhatsAppClientOptions {
  authDir: string;
  onMessage: (msg: InboundMessage) => void;
  onQR: (qr: string) => void;
  onStatus: (status: string, account?: WhatsAppAccountSummary | null) => void;
}

interface PendingInboundMediaEntry {
  msg: any | null;
  createdAt: number;
  resolvingPromise?: Promise<string[]>;
  resolvedMedia?: string[];
  resolvedAt?: number;
}

export class WhatsAppClient {
  private sock: any = null;
  private options: WhatsAppClientOptions;
  private reconnecting = false;
  private delayedMediaEnabled = false;
  private pendingInboundMedia = new Map<string, PendingInboundMediaEntry>();
  private static readonly MEDIA_TOKEN_TTL_MS = 5 * 60 * 1000;
  private static mediaDownloader = downloadMediaMessage;
  private static readonly supportedContentFields = new Set([
    'conversation',
    'extendedTextMessage',
    'imageMessage',
    'videoMessage',
    'documentMessage',
    'audioMessage',
  ]);

  private static readonly unsupportedContentLabels: Record<string, string> = {
    stickerMessage: 'sticker',
    locationMessage: 'location',
    liveLocationMessage: 'live location',
    contactMessage: 'contact',
    contactsArrayMessage: 'contacts',
    pollCreationMessage: 'poll',
    pollUpdateMessage: 'poll update',
    reactionMessage: 'reaction',
    buttonsResponseMessage: 'button response',
    templateButtonReplyMessage: 'template button reply',
    listResponseMessage: 'list response',
    orderMessage: 'order',
    productMessage: 'product',
    protocolMessage: 'protocol',
  };

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
    this.loadPendingInboundMedia();
  }

  setDelayedMediaEnabled(enabled: boolean): void {
    this.delayedMediaEnabled = enabled;
    if (!enabled) {
      this.pendingInboundMedia.clear();
      this.persistPendingInboundMedia();
    }
  }

  private pendingMediaStatePath(): string {
    return join(this.options.authDir, 'pending-inbound-media.json');
  }

  private static readonly persistedPendingMediaOmitKeys = new Set([
    'caption',
    'title',
    'fileName',
    'contextInfo',
    'jpegThumbnail',
    'thumbnailDirectPath',
    'thumbnailSha256',
    'thumbnailEncSha256',
    'streamingSidecar',
    'scansSidecar',
    'waveform',
  ]);

  private static serializePendingValue(value: any): any {
    if (typeof value === 'bigint') {
      return { __type: 'bigint', value: value.toString() };
    }
    if (Buffer.isBuffer(value)) {
      return { __type: 'buffer', value: value.toString('base64') };
    }
    if (value instanceof Uint8Array) {
      return { __type: 'buffer', value: Buffer.from(value).toString('base64') };
    }
    if (Array.isArray(value)) {
      return value.map((item) => WhatsAppClient.serializePendingValue(item));
    }
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value).map(([key, nested]) => [key, WhatsAppClient.serializePendingValue(nested)])
      );
    }
    return value;
  }

  private static deserializePendingValue(value: any): any {
    if (!value || typeof value !== 'object') return value;
    if (Array.isArray(value)) {
      return value.map((item) => WhatsAppClient.deserializePendingValue(item));
    }
    if (value.__type === 'buffer' && typeof value.value === 'string') {
      return Buffer.from(value.value, 'base64');
    }
    if (value.__type === 'bigint' && typeof value.value === 'string') {
      return BigInt(value.value);
    }
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [key, WhatsAppClient.deserializePendingValue(nested)])
    );
  }

  private static minimizePersistedPendingValue(value: any): any {
    if (!value || typeof value !== 'object') return value;
    if (Array.isArray(value)) {
      return value.map((item) => WhatsAppClient.minimizePersistedPendingValue(item));
    }
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !WhatsAppClient.persistedPendingMediaOmitKeys.has(key))
        .map(([key, nested]) => [key, WhatsAppClient.minimizePersistedPendingValue(nested)])
    );
  }

  private static serializePendingInboundMessageForPersistence(msg: any): any | null {
    const message = msg?.message;
    if (!message || typeof message !== 'object') return null;
    const mediaField = ['documentMessage', 'imageMessage', 'videoMessage', 'audioMessage']
      .find((key) => Boolean(message[key]));
    if (!mediaField) return null;
    const mediaPayload = message[mediaField];
    const minimizedMedia = WhatsAppClient.minimizePersistedPendingValue(
      WhatsAppClient.serializePendingValue(mediaPayload)
    );
    if (
      mediaField === 'documentMessage' &&
      minimizedMedia &&
      typeof minimizedMedia === 'object'
    ) {
      const explicitName = typeof mediaPayload?.fileName === 'string'
        ? mediaPayload.fileName
        : typeof mediaPayload?.title === 'string'
          ? mediaPayload.title
          : '';
      const ext = extname(explicitName) || '.bin';
      minimizedMedia.fileName = `attachment${ext}`;
    }

    return {
      key: {
        id: typeof msg?.key?.id === 'string' ? msg.key.id : '',
        remoteJid: typeof msg?.key?.remoteJid === 'string' ? msg.key.remoteJid : '',
        participant: typeof msg?.key?.participant === 'string' ? msg.key.participant : '',
        fromMe: Boolean(msg?.key?.fromMe),
      },
      message: {
        [mediaField]: minimizedMedia,
      },
    };
  }

  private persistPendingInboundMedia(): void {
    try {
      mkdirSync(this.options.authDir, { recursive: true });
      const path = this.pendingMediaStatePath();
      const tmp = `${path}.tmp`;
      const serialized = Object.fromEntries(
        Array.from(this.pendingInboundMedia.entries()).map(([token, entry]) => [
          token,
          {
            createdAt: entry.createdAt,
            msg: entry.msg === null ? null : WhatsAppClient.serializePendingInboundMessageForPersistence(entry.msg),
            resolvedMedia: entry.resolvedMedia,
            resolvedAt: entry.resolvedAt,
          },
        ])
      );
      writeFileSync(tmp, JSON.stringify(serialized, null, 2));
      renameSync(tmp, path);
    } catch (error) {
      console.error('Failed to persist pending WhatsApp media state:', error);
    }
  }

  private loadPendingInboundMedia(): void {
    try {
      const raw = readFileSync(this.pendingMediaStatePath(), 'utf-8');
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return;
      const now = Date.now();
      for (const [token, rawEntry] of Object.entries(parsed)) {
        if (!rawEntry || typeof rawEntry !== 'object') continue;
        const createdAt = Number((rawEntry as PendingInboundMediaEntry).createdAt || 0);
        if (!createdAt || now - createdAt > WhatsAppClient.MEDIA_TOKEN_TTL_MS) continue;
        this.pendingInboundMedia.set(token, {
          createdAt,
          msg: (rawEntry as PendingInboundMediaEntry).msg === null
            ? null
            : WhatsAppClient.deserializePendingValue((rawEntry as PendingInboundMediaEntry).msg),
          resolvedMedia: Array.isArray((rawEntry as PendingInboundMediaEntry).resolvedMedia)
            ? [...((rawEntry as PendingInboundMediaEntry).resolvedMedia as string[])]
            : undefined,
          resolvedAt: Number((rawEntry as PendingInboundMediaEntry).resolvedAt || 0) || undefined,
        });
      }
      this.prunePendingInboundMedia(now);
    } catch {
      // No persisted media cache yet or unreadable file.
    }
  }

  private resolveAccountSummary(stateCreds: any): WhatsAppAccountSummary | null {
    const user = this.sock?.user || stateCreds?.me || null;
    if (!user || typeof user !== 'object') return null;

    const rawId = typeof user.id === 'string' ? user.id : '';
    const phone = rawId ? rawId.split(':')[0].split('@')[0] : undefined;
    const name = typeof user.name === 'string' && user.name.trim() ? user.name.trim() : undefined;
    const id = rawId || undefined;

    if (!id && !phone && !name) return null;
    return { id, phone, name };
  }

  async connect(): Promise<void> {
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    this.sock = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, logger),
      },
      version,
      logger,
      printQRInTerminal: false,
      browser: ['lemonclaw', 'cli', VERSION],
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    if (this.sock.ws && typeof this.sock.ws.on === 'function') {
      this.sock.ws.on('error', (err: Error) => {
        console.error('WebSocket error:', err.message);
      });
    }

    this.sock.ev.on('connection.update', async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        console.log('\n📱 Scan this QR code with WhatsApp (Linked Devices):\n');
        qrcode.generate(qr, { small: true });
        this.options.onQR(qr);
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`Connection closed. Status: ${statusCode}, Will reconnect: ${shouldReconnect}`);
        this.options.onStatus('disconnected', null);

        if (shouldReconnect && !this.reconnecting) {
          this.reconnecting = true;
          console.log('Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.reconnecting = false;
            this.connect();
          }, 5000);
        }
      } else if (connection === 'open') {
        console.log('✅ Connected to WhatsApp');
        this.options.onStatus('connected', this.resolveAccountSummary(state.creds));
      }
    });

    this.sock.ev.on('creds.update', saveCreds);

    this.sock.ev.on('messages.upsert', async ({ messages, type }: { messages: any[]; type: string }) => {
      if (type !== 'notify') return;

      for (const msg of messages) {
        if (msg.key.fromMe) continue;
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const content = this.extractMessageContent(msg);
        if (!content) continue;
        const mediaToken = this.delayedMediaEnabled ? this.registerPendingInboundMedia(msg) : null;
        const media = this.delayedMediaEnabled ? [] : await this.downloadInboundMedia(msg);
        const context = this.extractContextInfo(msg);

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          mentions: context.mentions,
          quotedParticipant: context.quotedParticipant,
          media,
          mediaToken: mediaToken || undefined,
        });
      }
    });
  }

  private prunePendingInboundMedia(now: number = Date.now()): void {
    let changed = false;
    for (const [token, entry] of this.pendingInboundMedia.entries()) {
      if (now - entry.createdAt > WhatsAppClient.MEDIA_TOKEN_TTL_MS) {
        if (entry.resolvingPromise) continue;
        this.pendingInboundMedia.delete(token);
        changed = true;
      }
    }
    if (changed) this.persistPendingInboundMedia();
  }

  private hasInboundMedia(msg: any): boolean {
    const message = msg?.message;
    if (!message) return false;
    return Boolean(
      message.documentMessage ||
      message.imageMessage ||
      message.videoMessage ||
      message.audioMessage
    );
  }

  private registerPendingInboundMedia(msg: any): string | null {
    if (!this.hasInboundMedia(msg)) return null;
    this.prunePendingInboundMedia();
    const baseId = String(msg?.key?.id || 'msg').trim() || 'msg';
    let token = baseId;
    let suffix = 1;
    while (this.pendingInboundMedia.has(token)) {
      suffix += 1;
      token = `${baseId}:${suffix}`;
    }
    this.pendingInboundMedia.set(token, { msg, createdAt: Date.now() });
    this.persistPendingInboundMedia();
    return token;
  }

  private extractMessageContent(msg: any): string | null {
    const message = msg.message;
    if (!message) return null;

    // Text message
    if (message.conversation) {
      return message.conversation;
    }

    // Extended text (reply, link preview)
    if (message.extendedTextMessage?.text) {
      return message.extendedTextMessage.text;
    }

    // Image with caption
    if (message.imageMessage?.caption) {
      return `[Image] ${message.imageMessage.caption}`;
    }
    if (message.imageMessage) {
      return '[Image]';
    }

    // Video with caption
    if (message.videoMessage?.caption) {
      return `[Video] ${message.videoMessage.caption}`;
    }
    if (message.videoMessage) {
      return '[Video]';
    }

    // Document with caption
    if (message.documentMessage?.caption) {
      return `[Document] ${message.documentMessage.caption}`;
    }
    if (message.documentMessage) {
      const filename = message.documentMessage.fileName || message.documentMessage.title || 'document';
      return `[Document] ${filename}`;
    }

    // Voice/Audio message
    if (message.audioMessage) {
      return `[Voice Message]`;
    }

    const unsupported = this.describeUnsupportedMessage(message);
    if (unsupported) {
      return `[Unsupported WhatsApp message type: ${unsupported}]`;
    }

    return null;
  }

  private describeUnsupportedMessage(message: any): string | null {
    if (!message || typeof message !== 'object') return null;

    for (const [key, label] of Object.entries(WhatsAppClient.unsupportedContentLabels)) {
      if (message[key]) return label;
    }

    const fallbackKey = Object.keys(message).find(
      (key) => key.endsWith('Message') && !WhatsAppClient.supportedContentFields.has(key)
    );
    if (!fallbackKey) return null;

    return (
      WhatsAppClient.unsupportedContentLabels[fallbackKey] ||
      fallbackKey
        .replace(/Message$/, '')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .trim()
        .toLowerCase()
    );
  }

  private extractContextInfo(msg: any): { mentions: string[]; quotedParticipant: string } {
    const message = msg.message || {};
    const candidates = [
      message.extendedTextMessage,
      message.imageMessage,
      message.videoMessage,
      message.documentMessage,
      message.audioMessage,
      message.stickerMessage,
    ];

    for (const candidate of candidates) {
      const contextInfo = candidate?.contextInfo;
      if (!contextInfo) continue;
      return {
        mentions: Array.isArray(contextInfo.mentionedJid)
          ? contextInfo.mentionedJid.filter((value: unknown) => typeof value === 'string')
          : [],
        quotedParticipant: typeof contextInfo.participant === 'string' ? contextInfo.participant : '',
      };
    }

    return { mentions: [], quotedParticipant: '' };
  }

  async resolveInboundMedia(token: string): Promise<string[]> {
    this.prunePendingInboundMedia();
    const entry = this.pendingInboundMedia.get(token);
    if (!entry) {
      throw new Error(`unknown or expired media token: ${token}`);
    }
    if (entry.resolvedMedia) {
      return entry.resolvedMedia;
    }
    if (entry.resolvingPromise) {
      return entry.resolvingPromise;
    }

    entry.resolvingPromise = (async () => {
      try {
        const media = await this.downloadInboundMedia(entry.msg);
        if (!media.length && this.hasInboundMedia(entry.msg)) {
          throw new Error(`failed to materialize WhatsApp media for token ${token}`);
        }
        entry.resolvedMedia = media;
        entry.resolvedAt = Date.now();
        this.persistPendingInboundMedia();
        return media;
      } finally {
        entry.resolvingPromise = undefined;
      }
    })();
    return entry.resolvingPromise;
  }

  private async downloadInboundMedia(msg: any): Promise<string[]> {
    const message = msg.message;
    if (!message) return [];
    const media = message.documentMessage || message.imageMessage || message.videoMessage || message.audioMessage;
    if (!media) return [];

    try {
      const buffer = await WhatsAppClient.mediaDownloader(msg, 'buffer', {}, {
        logger: pino({ level: 'silent' }),
        reuploadRequest: async (m) => this.sock.updateMediaMessage(m),
      });
      const mediaDir = join(homedir(), '.lemonclaw', 'media', 'whatsapp');
      await mkdir(mediaDir, { recursive: true });

      const kind = message.documentMessage
        ? 'document'
        : message.imageMessage
          ? 'image'
          : message.videoMessage
            ? 'video'
            : 'audio';
      const explicitName =
        media.fileName ||
        media.title ||
        `${msg.key.id || 'msg'}${this.extensionForMedia(message, media.mimetype || '')}`;
      const safeName = basename(String(explicitName)).replace(/[^\w.\-\u4e00-\u9fff ]/g, '_');
      const filePath = join(mediaDir, `${msg.key.id || 'msg'}_${kind}_${safeName}`);
      await writeFile(filePath, buffer);
      return [filePath];
    } catch (error) {
      console.error('Failed to download WhatsApp media:', error);
      throw error;
    }
  }

  private extensionForMedia(message: any, mimeType: string): string {
    const lower = String(mimeType || '').toLowerCase();
    if (message.imageMessage) return extname(lower) || '.jpg';
    if (message.videoMessage) return extname(lower) || '.mp4';
    if (message.audioMessage) return extname(lower) || '.opus';
    if (message.documentMessage) {
      const slash = lower.indexOf('/');
      if (slash >= 0) {
        const subtype = lower.slice(slash + 1).split(';', 1)[0].trim();
        if (subtype) return `.${subtype.replace(/[^\w.+-]/g, '')}`;
      }
      return '.bin';
    }
    return '.bin';
  }

  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }
    await this.sock.sendMessage(to, { text });
  }

  async logout(): Promise<void> {
    if (this.sock?.logout && typeof this.sock.logout === 'function') {
      await this.sock.logout();
    }
    await this.disconnect();
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
