import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { PersistentWeixinEventQueue } from './event-queue.js';

test('PersistentWeixinEventQueue falls back to backup state when primary file is corrupt', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'weixin-event-queue-'));
  const queueFile = path.join(root, 'queue.json');
  process.env.WEIXIN_EVENT_QUEUE_FILE = queueFile;

  try {
    const queue = new PersistentWeixinEventQueue();
    queue.enqueue({
      type: 'message',
      accountId: 'bot-1',
      senderId: 'user-1',
      peerId: 'user-1',
      chatId: 'bot-1|user-1',
      content: 'first',
    });
    queue.enqueue({
      type: 'message',
      accountId: 'bot-1',
      senderId: 'user-2',
      peerId: 'user-2',
      chatId: 'bot-1|user-2',
      content: 'second',
    });

    const backupFile = `${queueFile}.bak`;
    const current = readFileSync(queueFile, 'utf-8');
    writeFileSync(backupFile, current, 'utf-8');
    writeFileSync(queueFile, '{"nextId": 3, "events": [', 'utf-8');

    const reloaded = new PersistentWeixinEventQueue();
    const events = reloaded.listAfter(0, 10);

    assert.equal(events.length, 2);
    assert.equal(events[0]?.content, 'first');
    assert.equal(events[1]?.content, 'second');
  } finally {
    delete process.env.WEIXIN_EVENT_QUEUE_FILE;
    rmSync(root, { recursive: true, force: true });
  }
});
