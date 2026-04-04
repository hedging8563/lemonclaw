import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test, { mock } from 'node:test';
import crypto from 'node:crypto';

import { MessageItemType } from './api.js';
import { encryptAesEcb } from './aes-ecb.js';
import { extractInboundMediaPaths, sendWeixinMediaFiles } from './media.js';
import { uploadFileAttachmentToWeixin } from './upload.js';

function installFetchMock() {
  const sendBodies: any[] = [];
  const fetchMock = mock.method(globalThis, 'fetch', async (input: any, init?: any) => {
    const url = String(input);
    if (url.includes('/ilink/bot/getuploadurl')) {
      return new Response(JSON.stringify({ upload_param: 'upload-param-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('upload-param-1')) {
      return new Response('', {
        status: 200,
        headers: { 'x-encrypted-param': 'download-param-1' },
      });
    }
    if (url.includes('/ilink/bot/sendmessage')) {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      sendBodies.push(body);
      return new Response(JSON.stringify({ ret: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    throw new Error(`unexpected fetch url: ${url}`);
  });
  return { sendBodies, fetchMock };
}

test('uploadFileAttachmentToWeixin rejects empty files', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-empty-'));
  try {
    const emptyFile = path.join(dir, 'empty.md');
    writeFileSync(emptyFile, '');

    await assert.rejects(
      uploadFileAttachmentToWeixin({
        filePath: emptyFile,
        toUserId: 'wx-user',
        baseUrl: 'https://example.weixin.local',
        cdnBaseUrl: 'https://cdn.weixin.local',
      }),
      /cannot be empty/,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('sendWeixinMediaFiles routes outbound audio as a file attachment', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-audio-'));
  const randomMock = mock.method(crypto, 'randomBytes', (size: number) => Buffer.alloc(size, 1));
  const { sendBodies, fetchMock } = installFetchMock();
  try {
    const audioFile = path.join(dir, 'clip.wav');
    writeFileSync(audioFile, 'not-empty-audio');

    const result = await sendWeixinMediaFiles({
      accountId: 'bot-1',
      to: 'wx-user',
      text: 'caption text',
      mediaPaths: [audioFile],
      contextToken: 'ctx-123',
      baseUrl: 'https://example.weixin.local',
      cdnBaseUrl: 'https://cdn.weixin.local',
    });

    assert.equal(result.messageIds.length, 1);
    assert.equal(sendBodies.length, 2);
    assert.equal(sendBodies[0].msg.item_list[0].type, 1);
    assert.equal(sendBodies[0].msg.item_list[0].text_item.text, 'caption text');
    assert.equal(sendBodies[1].msg.item_list[0].type, 4);
    assert.equal(sendBodies[1].msg.item_list[0].file_item.file_name, 'clip.wav');
    assert.equal(sendBodies[1].msg.item_list[0].file_item.len, String('not-empty-audio'.length));
    assert.equal(sendBodies[1].msg.item_list[0].file_item.media.aes_key, Buffer.alloc(16, 1).toString('base64'));
  } finally {
    fetchMock.mock.restore();
    randomMock.mock.restore();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('sendWeixinMediaFiles includes native image and video size fields', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-media-'));
  const randomMock = mock.method(crypto, 'randomBytes', (size: number) => Buffer.alloc(size, 2));
  const { sendBodies, fetchMock } = installFetchMock();
  try {
    const imageFile = path.join(dir, 'photo.jpg');
    const videoFile = path.join(dir, 'clip.mp4');
    writeFileSync(imageFile, 'image-bytes');
    writeFileSync(videoFile, 'video-bytes');

    await sendWeixinMediaFiles({
      accountId: 'bot-1',
      to: 'wx-user',
      text: 'caption text',
      mediaPaths: [imageFile, videoFile],
      contextToken: 'ctx-456',
      baseUrl: 'https://example.weixin.local',
      cdnBaseUrl: 'https://cdn.weixin.local',
    });

    const imagePayload = sendBodies[1].msg.item_list[0];
    const videoPayload = sendBodies[2].msg.item_list[0];

    assert.equal(imagePayload.type, 2);
    assert.ok(typeof imagePayload.image_item.mid_size === 'number');
    assert.ok(imagePayload.image_item.mid_size > 0);
    assert.equal(imagePayload.image_item.media.aes_key, Buffer.alloc(16, 2).toString('base64'));

    assert.equal(videoPayload.type, 5);
    assert.ok(typeof videoPayload.video_item.video_size === 'number');
    assert.ok(videoPayload.video_item.video_size > 0);
    assert.equal(videoPayload.video_item.media.aes_key, Buffer.alloc(16, 2).toString('base64'));
  } finally {
    fetchMock.mock.restore();
    randomMock.mock.restore();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('sendWeixinMediaFiles routes generic files through file attachments with binary aes key payload', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-file-'));
  const randomMock = mock.method(crypto, 'randomBytes', (size: number) => Buffer.alloc(size, 3));
  const { sendBodies, fetchMock } = installFetchMock();
  try {
    const filePath = path.join(dir, 'notes.txt');
    writeFileSync(filePath, 'hello-file');

    await sendWeixinMediaFiles({
      accountId: 'bot-1',
      to: 'wx-user',
      text: '',
      mediaPaths: [filePath],
      contextToken: 'ctx-file',
      baseUrl: 'https://example.weixin.local',
      cdnBaseUrl: 'https://cdn.weixin.local',
    });

    assert.equal(sendBodies.length, 1);
    const payload = sendBodies[0].msg.item_list[0];
    assert.equal(payload.type, 4);
    assert.equal(payload.file_item.file_name, 'notes.txt');
    assert.equal(payload.file_item.media.aes_key, Buffer.alloc(16, 3).toString('base64'));
  } finally {
    fetchMock.mock.restore();
    randomMock.mock.restore();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('extractInboundMediaPaths falls back to video thumbnail when main media download fails', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-inbound-video-'));
  const originalMediaDir = process.env.WEIXIN_MEDIA_DIR;
  process.env.WEIXIN_MEDIA_DIR = path.join(dir, 'weixin-media');
  const fetchMock = mock.method(globalThis, 'fetch', async (input: any) => {
    const url = String(input);
    if (url.includes('main-video')) {
      return new Response('missing', { status: 404 });
    }
    if (url.includes('thumb-image')) {
      return new Response(Buffer.from('thumb-bytes'), {
        status: 200,
        headers: { 'Content-Type': 'image/jpeg' },
      });
    }
    throw new Error(`unexpected fetch url: ${url}`);
  });

  try {
    const mediaPaths = await extractInboundMediaPaths({
      accountId: 'bot-1',
      cdnBaseUrl: 'https://cdn.weixin.local',
      message: {
        item_list: [
          {
            type: MessageItemType.VIDEO,
            video_item: {
              media: { encrypt_query_param: 'main-video' },
              thumb_media: { encrypt_query_param: 'thumb-image' },
            },
          },
        ],
      },
    });

    assert.equal(mediaPaths.length, 1);
    assert.match(mediaPaths[0], /image-.*\.jpg$/);
    assert.deepEqual(readFileSync(mediaPaths[0]), Buffer.from('thumb-bytes'));
  } finally {
    fetchMock.mock.restore();
    if (originalMediaDir == null) {
      delete process.env.WEIXIN_MEDIA_DIR;
    } else {
      process.env.WEIXIN_MEDIA_DIR = originalMediaDir;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

test('extractInboundMediaPaths decrypts inbound image with raw hex aeskey', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-inbound-image-'));
  const originalMediaDir = process.env.WEIXIN_MEDIA_DIR;
  process.env.WEIXIN_MEDIA_DIR = path.join(dir, 'weixin-media');
  const keyHex = '00112233445566778899aabbccddeeff';
  const plaintext = Buffer.from('jpeg-image-payload');
  const ciphertext = encryptAesEcb(plaintext, Buffer.from(keyHex, 'hex'));
  const fetchMock = mock.method(globalThis, 'fetch', async () => new Response(new Uint8Array(ciphertext), {
    status: 200,
    headers: { 'Content-Type': 'image/jpeg' },
  }));

  try {
    const mediaPaths = await extractInboundMediaPaths({
      accountId: 'bot-1',
      cdnBaseUrl: 'https://cdn.weixin.local',
      message: {
        item_list: [
          {
            type: MessageItemType.IMAGE,
            image_item: {
              aeskey: keyHex,
              media: { encrypt_query_param: 'encrypted-image' },
            },
          },
        ],
      },
    });

    assert.equal(mediaPaths.length, 1);
    assert.match(mediaPaths[0], /image-.*\.jpg$/);
    assert.deepEqual(readFileSync(mediaPaths[0]), plaintext);
  } finally {
    fetchMock.mock.restore();
    if (originalMediaDir == null) {
      delete process.env.WEIXIN_MEDIA_DIR;
    } else {
      process.env.WEIXIN_MEDIA_DIR = originalMediaDir;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

test('extractInboundMediaPaths decrypts inbound files with root-level raw hex aeskey', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-inbound-file-'));
  const originalMediaDir = process.env.WEIXIN_MEDIA_DIR;
  process.env.WEIXIN_MEDIA_DIR = path.join(dir, 'weixin-media');
  const keyHex = '11223344556677889900aabbccddeeff';
  const plaintext = Buffer.from('file-payload');
  const ciphertext = encryptAesEcb(plaintext, Buffer.from(keyHex, 'hex'));
  const fetchMock = mock.method(globalThis, 'fetch', async () => new Response(new Uint8Array(ciphertext), {
    status: 200,
    headers: { 'Content-Type': 'application/octet-stream' },
  }));

  try {
    const mediaPaths = await extractInboundMediaPaths({
      accountId: 'bot-1',
      cdnBaseUrl: 'https://cdn.weixin.local',
      message: {
        item_list: [
          {
            type: MessageItemType.FILE,
            file_item: {
              aeskey: keyHex,
              file_name: 'sample.bin',
              media: { encrypt_query_param: 'encrypted-file' },
            },
          },
        ],
      },
    });

    assert.equal(mediaPaths.length, 1);
    assert.match(mediaPaths[0], /file-.*\.bin$/);
    assert.deepEqual(readFileSync(mediaPaths[0]), plaintext);
  } finally {
    fetchMock.mock.restore();
    if (originalMediaDir == null) {
      delete process.env.WEIXIN_MEDIA_DIR;
    } else {
      process.env.WEIXIN_MEDIA_DIR = originalMediaDir;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

test('extractInboundMediaPaths decrypts inbound video with raw hex aeskey', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-inbound-video-hex-'));
  const originalMediaDir = process.env.WEIXIN_MEDIA_DIR;
  process.env.WEIXIN_MEDIA_DIR = path.join(dir, 'weixin-media');
  const keyHex = 'ffeeddccbbaa99887766554433221100';
  const plaintext = Buffer.from('mp4-video-payload');
  const ciphertext = encryptAesEcb(plaintext, Buffer.from(keyHex, 'hex'));
  const fetchMock = mock.method(globalThis, 'fetch', async () => new Response(new Uint8Array(ciphertext), {
    status: 200,
    headers: { 'Content-Type': 'video/mp4' },
  }));

  try {
    const mediaPaths = await extractInboundMediaPaths({
      accountId: 'bot-1',
      cdnBaseUrl: 'https://cdn.weixin.local',
      message: {
        item_list: [
          {
            type: MessageItemType.VIDEO,
            video_item: {
              aeskey: keyHex,
              media: { encrypt_query_param: 'encrypted-video' },
            },
          },
        ],
      },
    });

    assert.equal(mediaPaths.length, 1);
    assert.match(mediaPaths[0], /video-.*\.mp4$/);
    assert.deepEqual(readFileSync(mediaPaths[0]), plaintext);
  } finally {
    fetchMock.mock.restore();
    if (originalMediaDir == null) {
      delete process.env.WEIXIN_MEDIA_DIR;
    } else {
      process.env.WEIXIN_MEDIA_DIR = originalMediaDir;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});

test('extractInboundMediaPaths preserves inbound voice bytes when only root-level raw hex aeskey is present', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'weixin-inbound-voice-'));
  const originalMediaDir = process.env.WEIXIN_MEDIA_DIR;
  process.env.WEIXIN_MEDIA_DIR = path.join(dir, 'weixin-media');
  const keyHex = '0f1e2d3c4b5a69788796a5b4c3d2e1f0';
  const plaintext = Buffer.from('not-a-real-silk-frame');
  const ciphertext = encryptAesEcb(plaintext, Buffer.from(keyHex, 'hex'));
  const fetchMock = mock.method(globalThis, 'fetch', async () => new Response(new Uint8Array(ciphertext), {
    status: 200,
    headers: { 'Content-Type': 'audio/ogg' },
  }));

  try {
    const mediaPaths = await extractInboundMediaPaths({
      accountId: 'bot-1',
      cdnBaseUrl: 'https://cdn.weixin.local',
      message: {
        item_list: [
          {
            type: MessageItemType.VOICE,
            voice_item: {
              aeskey: keyHex,
              media: { encrypt_query_param: 'encrypted-voice' },
            },
          },
        ],
      },
    });

    assert.equal(mediaPaths.length, 1);
    assert.match(mediaPaths[0], /voice-.*\.(wav|silk)$/);
    if (mediaPaths[0].endsWith('.silk')) {
      assert.deepEqual(readFileSync(mediaPaths[0]), plaintext);
    }
  } finally {
    fetchMock.mock.restore();
    if (originalMediaDir == null) {
      delete process.env.WEIXIN_MEDIA_DIR;
    } else {
      process.env.WEIXIN_MEDIA_DIR = originalMediaDir;
    }
    rmSync(dir, { recursive: true, force: true });
  }
});
