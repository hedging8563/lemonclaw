/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { mkdir, writeFile } from 'fs/promises';
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

export class WhatsAppClient {
  private sock: any = null;
  private options: WhatsAppClientOptions;
  private reconnecting = false;

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
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
        const media = await this.downloadInboundMedia(msg);
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
        });
      }
    });
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

    return null;
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

  private async downloadInboundMedia(msg: any): Promise<string[]> {
    const message = msg.message;
    if (!message) return [];
    const media = message.documentMessage || message.imageMessage || message.videoMessage || message.audioMessage;
    if (!media) return [];

    try {
      const buffer = await downloadMediaMessage(msg, 'buffer', {}, {
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
      return [];
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
