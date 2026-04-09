import assert from 'node:assert/strict';
import test, { mock } from 'node:test';

import { encryptAesEcb } from './aes-ecb.js';
import { downloadAndDecryptBuffer, downloadPlainCdnBuffer } from './pic-decrypt.js';

test('downloadAndDecryptBuffer accepts raw hex aes keys', async () => {
  const keyHex = '00112233445566778899aabbccddeeff';
  const plaintext = Buffer.from('weixin-video-payload');
  const ciphertext = encryptAesEcb(plaintext, Buffer.from(keyHex, 'hex'));
  const fetchMock = mock.method(globalThis, 'fetch', async () => new Response(new Uint8Array(ciphertext), {
    status: 200,
    headers: { 'Content-Type': 'video/mp4' },
  }));

  try {
    const result = await downloadAndDecryptBuffer('download-token', keyHex, 'https://cdn.weixin.local');
    assert.deepEqual(result.buf, plaintext);
    assert.equal(result.contentType, 'video/mp4');
  } finally {
    fetchMock.mock.restore();
  }
});

test('downloadPlainCdnBuffer times out a hanging CDN request', async () => {
  const fetchMock = mock.method(globalThis, 'fetch', async (_input: any, init?: any) => {
    const signal: AbortSignal | undefined = init?.signal;
    await new Promise<never>((_resolve, reject) => {
      if (signal?.aborted) {
        reject(new Error('already aborted'));
        return;
      }
      signal?.addEventListener('abort', () => reject(new Error('aborted by signal')), { once: true });
    });
  });

  try {
    await assert.rejects(
      downloadPlainCdnBuffer('slow-download', 'https://cdn.weixin.local', 50),
      /timed out after 1000ms|timed out after 50ms/,
    );
  } finally {
    fetchMock.mock.restore();
  }
});
