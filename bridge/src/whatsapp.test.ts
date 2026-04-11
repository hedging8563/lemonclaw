import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { WhatsAppClient } from './whatsapp.js';

test('WhatsAppClient defers inbound media download until resolveInboundMedia', async () => {
  const tempHome = mkdtempSync(join(tmpdir(), 'lemonclaw-wa-'));
  const originalHome = process.env.HOME;
  process.env.HOME = tempHome;

  const client = new WhatsAppClient({
    authDir: '/tmp/lemonclaw-whatsapp-test',
    onMessage() {},
    onQR() {},
    onStatus() {},
  });
  (client as any).sock = { updateMediaMessage: async () => undefined };
  client.setDelayedMediaEnabled(true);

  const originalDownloader = (WhatsAppClient as any).mediaDownloader;
  (WhatsAppClient as any).mediaDownloader = async () => Buffer.from('doc-bytes');

  try {
    const msg = {
      key: { id: 'msg-1' },
      message: {
        documentMessage: {
          fileName: 'roman-history.docx',
          mimetype: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      },
    };

    const token = (client as any).registerPendingInboundMedia(msg);
    assert.equal(typeof token, 'string');
    assert.ok(token);
    assert.equal(existsSync(join(tempHome, '.lemonclaw', 'media', 'whatsapp')), false);

    const paths = await client.resolveInboundMedia(token);
    assert.equal(paths.length, 1);
    assert.ok(paths[0].endsWith('roman-history.docx'));
    assert.equal(existsSync(paths[0]), true);

    await assert.rejects(() => client.resolveInboundMedia(token), /unknown or expired media token/);
  } finally {
    (WhatsAppClient as any).mediaDownloader = originalDownloader;
    if (originalHome === undefined) {
      delete process.env.HOME;
    } else {
      process.env.HOME = originalHome;
    }
    rmSync(tempHome, { recursive: true, force: true });
  }
});
