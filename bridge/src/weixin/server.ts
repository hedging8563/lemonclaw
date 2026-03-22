import { createServer, IncomingMessage, ServerResponse } from 'http';
import { mkdirSync, renameSync, writeFileSync } from 'fs';
import { dirname } from 'path';

import {
  DEFAULT_WEIXIN_BASE_URL,
  DEFAULT_WEIXIN_CDN_BASE_URL,
  listWeixinAccounts,
  normalizeWeixinAccountId,
  removeWeixinAccount,
  saveWeixinAccount,
  stateFilePath,
  type WeixinAccountRecord,
} from './accounts.js';
import {
  getActiveWeixinLogin,
  listActiveWeixinLogins,
  startWeixinLoginWithQr,
  waitForWeixinLogin,
} from './login-qr.js';
import { WeixinMonitorHub } from './monitor.js';

interface BridgeState {
  status: 'idle' | 'starting' | 'qr' | 'scaned' | 'connected' | 'disconnected' | 'error';
  qr: string | null;
  sessionKey: string | null;
  account: WeixinAccountRecord | null;
  message?: string | null;
  error?: string | null;
  updatedAt: number;
  pid: number;
}

function parseJsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
    request.on('end', () => {
      if (chunks.length === 0) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf-8')) as Record<string, unknown>);
      } catch (error) {
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function initialState(): BridgeState {
  const accounts = listWeixinAccounts();
  return {
    status: accounts.length > 0 ? 'connected' : 'idle',
    qr: null,
    sessionKey: null,
    account: accounts[0] || null,
    message: accounts.length > 0 ? '微信桥已连接。' : null,
    error: null,
    updatedAt: Date.now(),
    pid: process.pid,
  };
}

export class WeixinBridgeServer {
  private server = createServer(this.handleRequest.bind(this));
  private state: BridgeState = initialState();
  private readonly trackedLogins = new Set<string>();
  private readonly monitorHub = new WeixinMonitorHub((account, error) => {
    if (error) {
      this.state = {
        ...this.state,
        status: 'error',
        account,
        error,
        message: error,
        updatedAt: Date.now(),
        pid: process.pid,
      };
    } else if (account) {
      this.state = {
        ...this.state,
        status: 'connected',
        account,
        error: null,
        message: account.lastInboundAt ? '微信消息同步中。' : '微信已连接，等待消息中。',
        updatedAt: Date.now(),
        pid: process.pid,
      };
    }
    this.persistState();
  });

  constructor(
    private readonly port: number,
    private readonly baseUrl: string,
    private readonly cdnBaseUrl: string,
    private readonly token?: string,
  ) {
    this.persistState();
  }

  private persistState(): void {
    const file = stateFilePath();
    mkdirSync(dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.state, null, 2));
    renameSync(tmp, file);
  }

  private json(response: ServerResponse, statusCode: number, payload: unknown): void {
    response.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(payload));
  }

  private unauthorized(response: ServerResponse): void {
    this.json(response, 401, { error: 'Unauthorized' });
  }

  private checkAuth(request: IncomingMessage): boolean {
    if (!this.token) return true;
    return request.headers.authorization === `Bearer ${this.token}`;
  }

  private snapshot() {
    return {
      ...this.state,
      accounts: listWeixinAccounts(),
      activeLogins: listActiveWeixinLogins().map((item) => ({
        sessionKey: item.sessionKey,
        status: item.status,
        startedAt: item.startedAt,
      })),
    };
  }

  private async trackLogin(sessionKey: string): Promise<void> {
    if (this.trackedLogins.has(sessionKey)) return;
    this.trackedLogins.add(sessionKey);
    try {
      while (true) {
        const active = getActiveWeixinLogin(sessionKey);
        if (!active) break;
        const result = await waitForWeixinLogin({
          sessionKey,
          baseUrl: this.baseUrl,
          timeoutMs: 2_000,
        });
        if (result.connected && result.botToken && result.accountId) {
          const accountId = normalizeWeixinAccountId(result.accountId);
          const account = saveWeixinAccount(accountId, {
            accountId,
            token: result.botToken,
            baseUrl: result.baseUrl || this.baseUrl,
            cdnBaseUrl: this.cdnBaseUrl || DEFAULT_WEIXIN_CDN_BASE_URL,
            userId: result.userId,
            lastError: '',
          });
          this.monitorHub.ensureMonitorForAccount(accountId);
          this.state = {
            ...this.state,
            status: 'connected',
            qr: null,
            sessionKey: null,
            account,
            message: result.message,
            error: null,
            updatedAt: Date.now(),
            pid: process.pid,
          };
          this.persistState();
          break;
        }

        if (result.status === 'expired') {
          this.state = {
            ...this.state,
            status: 'error',
            qr: null,
            sessionKey: null,
            account: null,
            message: result.message,
            error: result.message,
            updatedAt: Date.now(),
            pid: process.pid,
          };
          this.persistState();
          break;
        }

        this.state = {
          ...this.state,
          status: result.status === 'scaned' ? 'scaned' : 'qr',
          message: result.message,
          error: null,
          updatedAt: Date.now(),
          pid: process.pid,
        };
        this.persistState();
      }
    } catch (error) {
      this.state = {
        ...this.state,
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
        updatedAt: Date.now(),
        pid: process.pid,
      };
      this.persistState();
    } finally {
      this.trackedLogins.delete(sessionKey);
    }
  }

  private async handleRequest(request: IncomingMessage, response: ServerResponse): Promise<void> {
    try {
      if (!this.checkAuth(request)) {
        this.unauthorized(response);
        return;
      }

      const url = new URL(request.url || '/', `http://127.0.0.1:${this.port}`);
      if (request.method === 'GET' && url.pathname === '/health') {
        this.json(response, 200, { status: 'ok' });
        return;
      }

      if (request.method === 'GET' && url.pathname === '/state') {
        this.json(response, 200, this.snapshot());
        return;
      }

      if (request.method === 'GET' && url.pathname === '/accounts') {
        this.json(response, 200, { accounts: listWeixinAccounts() });
        return;
      }

      if (request.method === 'GET' && url.pathname === '/updates') {
        const cursor = Number(url.searchParams.get('cursor') || '0');
        const limit = Number(url.searchParams.get('limit') || '50');
        const waitMs = Number(url.searchParams.get('waitMs') || '25000');
        const payload = await this.monitorHub.getUpdatesAfter(Number.isFinite(cursor) ? cursor : 0, limit, waitMs);
        this.json(response, 200, {
          ...payload,
          running: true,
          accountCount: listWeixinAccounts().length,
        });
        return;
      }

      if (request.method === 'POST' && url.pathname === '/login/start') {
        const body = await parseJsonBody(request);
        const result = await startWeixinLoginWithQr({
          baseUrl: String(body.baseUrl || this.baseUrl || DEFAULT_WEIXIN_BASE_URL),
          accountId: typeof body.accountId === 'string' ? body.accountId : undefined,
          force: Boolean(body.force),
        });
        this.state = {
          ...this.state,
          status: 'qr',
          qr: result.qrcodeUrl || null,
          sessionKey: result.sessionKey,
          message: result.message,
          error: null,
          updatedAt: Date.now(),
          pid: process.pid,
        };
        this.persistState();
        void this.trackLogin(result.sessionKey);
        this.json(response, 200, this.snapshot());
        return;
      }

      if (request.method === 'POST' && url.pathname === '/send') {
        const body = await parseJsonBody(request);
        const accountId = String(body.accountId || '').trim();
        const to = String(body.to || '').trim();
        const text = String(body.text || '');
        const mediaPaths = Array.isArray(body.mediaPaths)
          ? body.mediaPaths.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
          : [];
        if (!accountId || !to || (!text.trim() && mediaPaths.length === 0)) {
          this.json(response, 400, { error: 'accountId, to, and text or mediaPaths are required' });
          return;
        }
        const result = await this.monitorHub.sendText({
          accountId,
          to,
          text,
          contextToken: typeof body.contextToken === 'string' ? body.contextToken : undefined,
          mediaPaths,
        });
        this.json(response, 200, { ok: true, ...result });
        return;
      }

      if (request.method === 'POST' && url.pathname === '/disconnect') {
        const body = await parseJsonBody(request);
        const accountId = typeof body.accountId === 'string' ? normalizeWeixinAccountId(body.accountId) : undefined;
        if (accountId) {
          this.monitorHub.stopMonitor(accountId);
        } else {
          this.monitorHub.stopAll();
        }
        removeWeixinAccount(accountId);
        const accounts = listWeixinAccounts();
        this.state = {
          ...this.state,
          status: accounts.length > 0 ? 'connected' : 'disconnected',
          qr: null,
          sessionKey: null,
          account: accounts[0] || null,
          message: accounts.length > 0 ? '已断开指定微信账号。' : '已断开微信连接。',
          error: null,
          updatedAt: Date.now(),
          pid: process.pid,
        };
        this.persistState();
        this.json(response, 200, this.snapshot());
        return;
      }

      this.json(response, 404, { error: 'Not found' });
    } catch (error) {
      this.state = {
        ...this.state,
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
        updatedAt: Date.now(),
        pid: process.pid,
      };
      this.persistState();
      this.json(response, 500, { error: this.state.error });
    }
  }

  async start(): Promise<void> {
    this.monitorHub.ensureMonitors();
    await new Promise<void>((resolve) => {
      this.server.listen(this.port, '127.0.0.1', () => resolve());
    });
  }

  async stop(): Promise<void> {
    this.monitorHub.stopAll();
    await new Promise<void>((resolve, reject) => {
      this.server.close((error) => (error ? reject(error) : resolve()));
    });
  }
}
