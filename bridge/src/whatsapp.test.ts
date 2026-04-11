import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, existsSync, readFileSync, rmSync } from 'node:fs';
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
  let downloadCalls = 0;

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

    (WhatsAppClient as any).mediaDownloader = async () => {
      downloadCalls += 1;
      return Buffer.from('doc-bytes');
    };

    const paths = await client.resolveInboundMedia(token);
    assert.equal(paths.length, 1);
    assert.ok(paths[0].endsWith('roman-history.docx'));
    assert.equal(existsSync(paths[0]), true);

    const duplicatePaths = await client.resolveInboundMedia(token);
    assert.deepEqual(duplicatePaths, paths);
    assert.equal(downloadCalls, 1);
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

test('WhatsAppClient restores pending inbound media cache across client recreation', async () => {
  const tempHome = mkdtempSync(join(tmpdir(), 'lemonclaw-wa-restore-'));
  const authDir = join(tempHome, 'auth');
  const originalHome = process.env.HOME;
  process.env.HOME = tempHome;

  const originalDownloader = (WhatsAppClient as any).mediaDownloader;
  (WhatsAppClient as any).mediaDownloader = async () => Buffer.from('doc-bytes');

  try {
    const msg = {
      key: { id: 'msg-restore' },
      message: {
        documentMessage: {
          fileName: 'restored.docx',
          caption: 'customer secret',
          mimetype: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      },
    };

    const client1 = new WhatsAppClient({
      authDir,
      onMessage() {},
      onQR() {},
      onStatus() {},
    });
    (client1 as any).sock = { updateMediaMessage: async () => undefined };
    client1.setDelayedMediaEnabled(true);
    const token = (client1 as any).registerPendingInboundMedia(msg);
    assert.equal(typeof token, 'string');
    const persisted = readFileSync(join(authDir, 'pending-inbound-media.json'), 'utf-8');
    assert.equal(persisted.includes('customer secret'), false);
    assert.equal(persisted.includes('restored.docx'), false);

    const client2 = new WhatsAppClient({
      authDir,
      onMessage() {},
      onQR() {},
      onStatus() {},
    });
    (client2 as any).sock = { updateMediaMessage: async () => undefined };
    client2.setDelayedMediaEnabled(true);

    const paths = await client2.resolveInboundMedia(token);
    assert.equal(paths.length, 1);
    assert.ok(paths[0].endsWith('attachment.docx'));
    assert.equal(existsSync(paths[0]), true);
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
