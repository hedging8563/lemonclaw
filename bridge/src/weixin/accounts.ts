import { mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs';
import { dirname, join } from 'path';

export const DEFAULT_WEIXIN_BASE_URL = 'https://ilinkai.weixin.qq.com';
export const DEFAULT_WEIXIN_CDN_BASE_URL = 'https://novac2c.cdn.weixin.qq.com/c2c';

export interface WeixinAccountRecord {
  accountId: string;
  token?: string;
  baseUrl?: string;
  cdnBaseUrl?: string;
  userId?: string;
  syncBuf?: string;
  contextTokens?: Record<string, string>;
  lastInboundAt?: number;
  lastError?: string;
  savedAt?: string;
}

function accountsDir(): string {
  return process.env.WEIXIN_ACCOUNTS_DIR || join(process.env.HOME || '/tmp', '.lemonclaw', 'weixin-accounts');
}

function ensureAccountsDir(): string {
  const dir = accountsDir();
  mkdirSync(dir, { recursive: true });
  return dir;
}

export function mediaDir(): string {
  const dir = process.env.WEIXIN_MEDIA_DIR || join(ensureAccountsDir(), '..', 'weixin-media');
  mkdirSync(dir, { recursive: true });
  return dir;
}

export function normalizeWeixinAccountId(raw: string): string {
  return String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function accountFile(accountId: string): string {
  return join(ensureAccountsDir(), `${normalizeWeixinAccountId(accountId)}.json`);
}

export function saveWeixinAccount(accountId: string, update: Partial<WeixinAccountRecord>): WeixinAccountRecord {
  const normalized = normalizeWeixinAccountId(accountId);
  const existing = loadWeixinAccount(normalized) || { accountId: normalized };
  const next: WeixinAccountRecord = {
    ...existing,
    ...update,
    accountId: normalized,
    baseUrl: (update.baseUrl || existing.baseUrl || DEFAULT_WEIXIN_BASE_URL).trim(),
    cdnBaseUrl: (update.cdnBaseUrl || existing.cdnBaseUrl || DEFAULT_WEIXIN_CDN_BASE_URL).trim(),
    savedAt: new Date().toISOString(),
  };
  writeFileSync(accountFile(normalized), JSON.stringify(next, null, 2));
  return next;
}

export function loadWeixinAccount(accountId: string): WeixinAccountRecord | null {
  const file = accountFile(accountId);
  try {
    return JSON.parse(readFileSync(file, 'utf-8')) as WeixinAccountRecord;
  } catch {
    return null;
  }
}

export function saveWeixinContextToken(accountId: string, peerId: string, contextToken: string): WeixinAccountRecord {
  const normalizedPeerId = String(peerId || '').trim();
  if (!normalizedPeerId) {
    return saveWeixinAccount(accountId, {});
  }

  const existing = loadWeixinAccount(accountId) || { accountId: normalizeWeixinAccountId(accountId) };
  return saveWeixinAccount(accountId, {
    contextTokens: {
      ...(existing.contextTokens || {}),
      [normalizedPeerId]: String(contextToken || ''),
    },
  });
}

export function loadWeixinContextToken(accountId: string, peerId: string): string | undefined {
  const normalizedPeerId = String(peerId || '').trim();
  if (!normalizedPeerId) return undefined;
  const account = loadWeixinAccount(accountId);
  const token = account?.contextTokens?.[normalizedPeerId];
  return typeof token === 'string' && token.trim().length > 0 ? token : undefined;
}

export function listWeixinAccounts(): WeixinAccountRecord[] {
  const dir = ensureAccountsDir();
  const items = readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name): WeixinAccountRecord | null => {
      const file = join(dir, name);
      try {
        const data = JSON.parse(readFileSync(file, 'utf-8')) as WeixinAccountRecord;
        const mtime = statSync(file).mtime.toISOString();
        return { ...data, savedAt: data.savedAt || mtime };
      } catch {
        return null;
      }
    });

  return items
    .filter((item): item is WeixinAccountRecord => item !== null)
    .sort((left, right) => String(right.savedAt || '').localeCompare(String(left.savedAt || '')));
}

export function removeWeixinAccount(accountId?: string): void {
  if (accountId) {
    rmSync(accountFile(accountId), { force: true });
    return;
  }
  rmSync(ensureAccountsDir(), { recursive: true, force: true });
  mkdirSync(ensureAccountsDir(), { recursive: true });
}

export function stateFilePath(): string {
  const file = process.env.WEIXIN_BRIDGE_STATE_FILE || join(process.env.HOME || '/tmp', '.lemonclaw', 'weixin-bridge-state.json');
  mkdirSync(dirname(file), { recursive: true });
  return file;
}

export function eventQueueFilePath(): string {
  const file = process.env.WEIXIN_EVENT_QUEUE_FILE || join(process.env.HOME || '/tmp', '.lemonclaw', 'weixin-event-queue.json');
  mkdirSync(dirname(file), { recursive: true });
  return file;
}
