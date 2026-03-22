import { randomUUID } from 'crypto';

import { fetchWeixinQRCode, pollWeixinQRStatus } from './api.js';

export interface ActiveWeixinLogin {
  sessionKey: string;
  qrcode: string;
  qrcodeUrl: string;
  startedAt: number;
  status: 'wait' | 'scaned' | 'confirmed' | 'expired';
}

export interface WeixinQrStartResult {
  sessionKey: string;
  qrcodeUrl?: string;
  message: string;
}

export interface WeixinQrWaitResult {
  connected: boolean;
  message: string;
  botToken?: string;
  accountId?: string;
  baseUrl?: string;
  userId?: string;
  status?: string;
}

const ACTIVE_LOGIN_TTL_MS = 5 * 60_000;
const activeLogins = new Map<string, ActiveWeixinLogin>();

export function listActiveWeixinLogins(): ActiveWeixinLogin[] {
  return [...activeLogins.values()];
}

export function getActiveWeixinLogin(sessionKey: string): ActiveWeixinLogin | null {
  return activeLogins.get(sessionKey) || null;
}

export async function startWeixinLoginWithQr(params: {
  baseUrl: string;
  accountId?: string;
  force?: boolean;
}): Promise<WeixinQrStartResult> {
  const sessionKey = params.accountId || randomUUID();
  const existing = activeLogins.get(sessionKey);
  if (!params.force && existing && Date.now() - existing.startedAt < ACTIVE_LOGIN_TTL_MS) {
    return {
      sessionKey,
      qrcodeUrl: existing.qrcodeUrl,
      message: '二维码已就绪，请使用微信扫码。',
    };
  }

  const qr = await fetchWeixinQRCode(params.baseUrl);
  activeLogins.set(sessionKey, {
    sessionKey,
    qrcode: qr.qrcode,
    qrcodeUrl: qr.qrcode_img_content,
    startedAt: Date.now(),
    status: 'wait',
  });

  return {
    sessionKey,
    qrcodeUrl: qr.qrcode_img_content,
    message: '使用微信扫描二维码完成连接。',
  };
}

export async function waitForWeixinLogin(params: {
  sessionKey: string;
  baseUrl: string;
  timeoutMs?: number;
}): Promise<WeixinQrWaitResult> {
  const login = activeLogins.get(params.sessionKey);
  if (!login) {
    return { connected: false, message: '当前没有进行中的微信登录。', status: 'missing' };
  }

  const deadline = Date.now() + Math.max(params.timeoutMs ?? 2_000, 1_000);
  while (Date.now() < deadline) {
    const status = await pollWeixinQRStatus(params.baseUrl, login.qrcode);
    login.status = status.status;
    if (status.status === 'confirmed' && status.bot_token && status.ilink_bot_id) {
      activeLogins.delete(params.sessionKey);
      return {
        connected: true,
        message: '微信连接成功。',
        botToken: status.bot_token,
        accountId: status.ilink_bot_id,
        baseUrl: status.baseurl || params.baseUrl,
        userId: status.ilink_user_id,
        status: status.status,
      };
    }
    if (status.status === 'expired') {
      activeLogins.delete(params.sessionKey);
      return { connected: false, message: '二维码已过期，请重新生成。', status: 'expired' };
    }
    if (status.status === 'scaned') {
      return { connected: false, message: '已扫码，请在微信中确认。', status: 'scaned' };
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return { connected: false, message: '等待扫码中。', status: login.status };
}
