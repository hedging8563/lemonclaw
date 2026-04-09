import assert from 'node:assert/strict';
import test, { mock } from 'node:test';

import {
  getActiveWeixinLogin,
  listActiveWeixinLogins,
  startWeixinLoginWithQr,
  waitForWeixinLogin,
} from './login-qr.js';

test('waitForWeixinLogin keeps polling on the baseUrl used to create the QR', async () => {
  const chosenBaseUrl = 'https://chosen.weixin.local';
  const wrongBaseUrl = 'https://default.weixin.local';
  let pollCount = 0;

  const fetchMock = mock.method(globalThis, 'fetch', async (input: any) => {
    const url = new URL(String(input));

    assert.equal(url.origin, chosenBaseUrl);

    if (url.pathname.endsWith('/ilink/bot/get_bot_qrcode')) {
      return new Response(JSON.stringify({
        qrcode: 'qr-123',
        qrcode_img_content: 'data:image/png;base64,qr-123',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname.endsWith('/ilink/bot/get_qrcode_status')) {
      pollCount += 1;
      return new Response(JSON.stringify(
        pollCount === 1
          ? { status: 'wait' }
          : {
              status: 'confirmed',
              bot_token: 'bot-token-123',
              ilink_bot_id: 'bot-account-123',
              ilink_user_id: 'user-123',
            },
      ), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    throw new Error(`unexpected fetch path: ${url.pathname}`);
  });

  try {
    const started = await startWeixinLoginWithQr({ baseUrl: chosenBaseUrl, force: true });
    const active = getActiveWeixinLogin(started.sessionKey);
    const activeLogins = listActiveWeixinLogins();

    assert.ok(active);
    assert.equal(active.baseUrl, chosenBaseUrl);
    assert.equal(activeLogins[0]?.baseUrl, chosenBaseUrl);

    const result = await waitForWeixinLogin({
      sessionKey: started.sessionKey,
      baseUrl: wrongBaseUrl,
      timeoutMs: 1_500,
    });

    assert.equal(result.connected, true);
    assert.equal(result.baseUrl, chosenBaseUrl);
    assert.equal(result.botToken, 'bot-token-123');
    assert.equal(pollCount, 2);
  } finally {
    fetchMock.mock.restore();
  }
});
