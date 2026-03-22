import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test, { mock } from 'node:test';
import crypto from 'node:crypto';

import { sendWeixinMediaFiles } from './media.js';
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

    assert.equal(videoPayload.type, 5);
    assert.ok(typeof videoPayload.video_item.video_size === 'number');
    assert.ok(videoPayload.video_item.video_size > 0);
  } finally {
    fetchMock.mock.restore();
    randomMock.mock.restore();
    rmSync(dir, { recursive: true, force: true });
  }
});
