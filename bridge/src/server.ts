/**
 * WebSocket server for Python-Node.js bridge communication.
 * Security: binds to 127.0.0.1 only; optional BRIDGE_TOKEN auth.
 */

import { mkdirSync, renameSync, writeFileSync } from 'fs';
import { dirname } from 'path';
import { WebSocketServer, WebSocket } from 'ws';
import { WhatsAppClient, InboundMessage, WhatsAppAccountSummary } from './whatsapp.js';

interface SendCommand {
  type: 'send';
  to: string;
  text: string;
}

interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';
  [key: string]: unknown;
}

export class BridgeServer {
  private wss: WebSocketServer | null = null;
  private wa: WhatsAppClient | null = null;
  private clients: Set<WebSocket> = new Set();
  private lastStatus: string | null = null;
  private lastQR: string | null = null;
  private lastAccount: WhatsAppAccountSummary | null = null;

  constructor(private port: number, private authDir: string, private token?: string, private stateFile?: string) {}

  private persistState(): void {
    if (!this.stateFile) return;
    try {
      mkdirSync(dirname(this.stateFile), { recursive: true });
      const tmp = `${this.stateFile}.tmp`;
      writeFileSync(tmp, JSON.stringify({
        status: this.lastStatus,
        qr: this.lastQR,
        account: this.lastAccount,
        pid: process.pid,
        updated_at: Date.now() / 1000,
      }, null, 2));
      renameSync(tmp, this.stateFile);
    } catch (error) {
      console.error('Failed to persist bridge state:', error);
    }
  }

  async start(): Promise<void> {
    this.lastStatus = 'starting';
    this.persistState();
    this.wss = new WebSocketServer({ host: '127.0.0.1', port: this.port });
    console.log(`🌉 Bridge server listening on ws://127.0.0.1:${this.port}`);
    if (this.token) console.log('🔒 Token authentication enabled');

    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),
      onQR: (qr) => this.broadcast({ type: 'qr', qr }),
      onStatus: (status, account) => this.broadcast({ type: 'status', status, account }),
    });

    this.wss.on('connection', (ws) => {
      if (this.token) {
        const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
        ws.once('message', (data) => {
          clearTimeout(timeout);
          try {
            const msg = JSON.parse(data.toString());
            if (msg.type === 'auth' && msg.token === this.token) {
              console.log('🔗 Python client authenticated');
              this.setupClient(ws);
            } else {
              ws.close(4003, 'Invalid token');
            }
          } catch {
            ws.close(4003, 'Invalid auth message');
          }
        });
      } else {
        console.log('🔗 Python client connected');
        this.setupClient(ws);
      }
    });

    await this.wa.connect();
  }

  private setupClient(ws: WebSocket): void {
    this.clients.add(ws);
    if (this.lastStatus) {
      ws.send(JSON.stringify({ type: 'status', status: this.lastStatus, account: this.lastAccount }));
    }
    if (this.lastQR) {
      ws.send(JSON.stringify({ type: 'qr', qr: this.lastQR }));
    }

    ws.on('message', async (data) => {
      try {
        const cmd = JSON.parse(data.toString()) as SendCommand;
        await this.handleCommand(cmd);
        ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
      } catch (error) {
        console.error('Error handling command:', error);
        ws.send(JSON.stringify({ type: 'error', error: String(error) }));
      }
    });

    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  private async handleCommand(cmd: SendCommand): Promise<void> {
    if (cmd.type === 'send' && this.wa) {
      await this.wa.sendMessage(cmd.to, cmd.text);
    }
  }

  private broadcast(msg: BridgeMessage): void {
    if (msg.type === 'status') {
      this.lastStatus = String(msg.status || 'unknown');
      this.lastAccount = (msg.account as WhatsAppAccountSummary | null | undefined) || null;
      if (this.lastStatus === 'connected') this.lastQR = null;
    }
    if (msg.type === 'qr') {
      this.lastStatus = 'qr';
      this.lastQR = typeof msg.qr === 'string' ? msg.qr : null;
    }
    if (msg.type === 'error') {
      this.lastStatus = 'error';
    }
    this.persistState();

    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  async stop(): Promise<void> {
    this.lastStatus = 'stopped';
    this.lastQR = null;
    this.persistState();

    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
