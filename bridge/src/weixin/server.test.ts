import assert from 'node:assert/strict';
import { createServer as createNetServer } from 'node:net';
import { request } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test, { mock } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';

import { WeixinBridgeServer } from './server.js';

async function getFreePort(): Promise<number> {
  return await new Promise<number>((resolve, reject) => {
    const probe = createNetServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address();
      if (!address || typeof address === 'string') {
        probe.close(() => reject(new Error('failed to read probe port')));
        return;
      }
      const port = address.port;
      probe.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function requestJson(port: number, method: 'GET' | 'POST', pathname: string, body?: unknown): Promise<{ status: number; json: any }> {
  return await new Promise<{ status: number; json: any }>((resolve, reject) => {
    const payload = body === undefined ? '' : JSON.stringify(body);
    const req = request({
      hostname: '127.0.0.1',
      port,
      path: pathname,
      method,
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) }),
      },
    }, (res) => {
      let raw = '';
      res.setEncoding('utf-8');
      res.on('data', (chunk) => { raw += chunk; });
      res.on('end', () => {
        resolve({
          status: res.statusCode ?? 0,
          json: raw.length > 0 ? JSON.parse(raw) : {},
        });
      });
    });

    req.once('error', reject);
    if (body !== undefined) {
      req.write(payload);
    }
    req.end();
  });
}

test('WeixinBridgeServer keeps login polling on the requested baseUrl', async () => {
  const tmpRoot = mkdtempSync(path.join(tmpdir(), 'weixin-bridge-server-'));
  const originalEnv = {
    WEIXIN_ACCOUNTS_DIR: process.env.WEIXIN_ACCOUNTS_DIR,
    WEIXIN_BRIDGE_STATE_FILE: process.env.WEIXIN_BRIDGE_STATE_FILE,
    WEIXIN_EVENT_QUEUE_FILE: process.env.WEIXIN_EVENT_QUEUE_FILE,
  };
  const port = await getFreePort();
  const defaultBaseUrl = 'https://default.weixin.local';
  const chosenBaseUrl = 'https://chosen.weixin.local';
  const cdnBaseUrl = 'https://cdn.weixin.local';
  let qrcodeFetches = 0;
  let statusFetches = 0;

  process.env.WEIXIN_ACCOUNTS_DIR = path.join(tmpRoot, 'accounts');
  process.env.WEIXIN_BRIDGE_STATE_FILE = path.join(tmpRoot, 'state.json');
  process.env.WEIXIN_EVENT_QUEUE_FILE = path.join(tmpRoot, 'events.json');

  const fetchMock = mock.method(globalThis, 'fetch', async (input: any) => {
    const url = new URL(String(input));
    assert.equal(url.origin, chosenBaseUrl);

    if (url.pathname.endsWith('/ilink/bot/get_bot_qrcode')) {
      qrcodeFetches += 1;
      return new Response(JSON.stringify({
        qrcode: 'qr-bridge-123',
        qrcode_img_content: 'data:image/png;base64,qr-bridge-123',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname.endsWith('/ilink/bot/get_qrcode_status')) {
      statusFetches += 1;
      return new Response(JSON.stringify(
        statusFetches === 1
          ? { status: 'scaned' }
          : {
              status: 'confirmed',
              bot_token: 'bot-token-bridge-123',
              ilink_bot_id: 'bot-account-bridge-123',
              ilink_user_id: 'user-bridge-123',
            },
      ), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname.endsWith('/ilink/bot/getupdates')) {
      await delay(25);
      return new Response(JSON.stringify({
        ret: 0,
        errcode: 0,
        msgs: [],
        get_updates_buf: 'buf-bridge-123',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    throw new Error(`unexpected fetch path: ${url.pathname}`);
  });

  const server = new WeixinBridgeServer(port, defaultBaseUrl, cdnBaseUrl);
  let started = false;
  try {
    await server.start();
    started = true;

    const startResponse = await requestJson(port, 'POST', '/login/start', { baseUrl: chosenBaseUrl, force: true });
    assert.equal(startResponse.status, 200);

    let state: any = startResponse.json;
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline) {
      const current = await requestJson(port, 'GET', '/state');
      state = current.json;
      if (state.status === 'connected') {
        break;
      }
      await delay(100);
    }

    assert.equal(state.status, 'connected');
    assert.equal(state.account.baseUrl, chosenBaseUrl);
    assert.equal(qrcodeFetches, 1);
    assert.equal(statusFetches, 2);

    const disconnectResponse = await requestJson(port, 'POST', '/disconnect', {
      accountId: state.account.accountId,
    });
    assert.equal(disconnectResponse.status, 200);

    let disconnected: any = disconnectResponse.json;
    const disconnectDeadline = Date.now() + 3_000;
    while (Date.now() < disconnectDeadline) {
      const current = await requestJson(port, 'GET', '/state');
      disconnected = current.json;
      if (disconnected.status === 'disconnected' || disconnected.status === 'idle') {
        break;
      }
      await delay(50);
    }
    assert.ok(disconnected.status === 'disconnected' || disconnected.status === 'idle');
  } finally {
    fetchMock.mock.restore();
    if (started) {
      await server.stop();
    }
    if (originalEnv.WEIXIN_ACCOUNTS_DIR === undefined) {
      delete process.env.WEIXIN_ACCOUNTS_DIR;
    } else {
      process.env.WEIXIN_ACCOUNTS_DIR = originalEnv.WEIXIN_ACCOUNTS_DIR;
    }
    if (originalEnv.WEIXIN_BRIDGE_STATE_FILE === undefined) {
      delete process.env.WEIXIN_BRIDGE_STATE_FILE;
    } else {
      process.env.WEIXIN_BRIDGE_STATE_FILE = originalEnv.WEIXIN_BRIDGE_STATE_FILE;
    }
    if (originalEnv.WEIXIN_EVENT_QUEUE_FILE === undefined) {
      delete process.env.WEIXIN_EVENT_QUEUE_FILE;
    } else {
      process.env.WEIXIN_EVENT_QUEUE_FILE = originalEnv.WEIXIN_EVENT_QUEUE_FILE;
    }
    rmSync(tmpRoot, { recursive: true, force: true });
  }
});
