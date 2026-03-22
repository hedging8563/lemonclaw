import { mkdirSync, writeFileSync } from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';

import {
  MessageItemType,
  MessageState,
  MessageType,
  sendMessage,
  type MessageItem,
  type SendMessageReq,
  type WeixinMessage,
} from './api.js';
import { mediaDir } from './accounts.js';
import { getExtensionFromContentTypeOrUrl, getMimeFromFilename } from './mime.js';
import { downloadAndDecryptBuffer, downloadPlainCdnBuffer } from './pic-decrypt.js';
import {
  getOutboundMediaMime,
  uploadFileAttachmentToWeixin,
  uploadFileToWeixin,
  uploadVideoToWeixin,
} from './upload.js';
import { WEIXIN_MEDIA_MAX_BYTES } from './limits.js';

function ensureAccountMediaDir(accountId: string): string {
  const dir = path.join(mediaDir(), accountId);
  mkdirSync(dir, { recursive: true });
  return dir;
}

function saveMediaBuffer(params: {
  accountId: string;
  buf: Buffer;
  ext: string;
  prefix: string;
}): string {
  if (params.buf.length > WEIXIN_MEDIA_MAX_BYTES) {
    throw new Error(`Weixin media too large: ${params.buf.length} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
  }
  const dir = ensureAccountMediaDir(params.accountId);
  const file = path.join(dir, `${params.prefix}-${randomUUID()}${params.ext}`);
  writeFileSync(file, params.buf);
  return file;
}

function encodeAesKeyHexToBase64(aesKeyHex: string): string {
  return Buffer.from(aesKeyHex, 'hex').toString('base64');
}

async function downloadMediaItem(params: {
  accountId: string;
  item: MessageItem;
  cdnBaseUrl: string;
}): Promise<string | null> {
  const { accountId, item, cdnBaseUrl } = params;
  if (item.type === MessageItemType.IMAGE && item.image_item?.media?.encrypt_query_param) {
    const key = item.image_item.aeskey
      ? encodeAesKeyHexToBase64(item.image_item.aeskey)
      : item.image_item.media.aes_key;
    const result = key
      ? await downloadAndDecryptBuffer(item.image_item.media.encrypt_query_param, key, cdnBaseUrl)
      : await downloadPlainCdnBuffer(item.image_item.media.encrypt_query_param, cdnBaseUrl);
    const ext = getExtensionFromContentTypeOrUrl(result.contentType, `https://example.local/fallback.jpg`);
    return saveMediaBuffer({ accountId, buf: result.buf, ext: ext === '.bin' ? '.jpg' : ext, prefix: 'image' });
  }

  if (item.type === MessageItemType.FILE && item.file_item?.media?.encrypt_query_param && item.file_item.media.aes_key) {
    const result = await downloadAndDecryptBuffer(item.file_item.media.encrypt_query_param, item.file_item.media.aes_key, cdnBaseUrl);
    const ext = path.extname(item.file_item.file_name || '') || getExtensionFromContentTypeOrUrl(result.contentType, 'https://example.local/file.bin');
    return saveMediaBuffer({ accountId, buf: result.buf, ext: ext || '.bin', prefix: 'file' });
  }

  if (item.type === MessageItemType.VIDEO && item.video_item?.media?.encrypt_query_param && item.video_item.media.aes_key) {
    const result = await downloadAndDecryptBuffer(item.video_item.media.encrypt_query_param, item.video_item.media.aes_key, cdnBaseUrl);
    const ext = getExtensionFromContentTypeOrUrl(result.contentType, 'https://example.local/video.mp4');
    return saveMediaBuffer({ accountId, buf: result.buf, ext: ext === '.bin' ? '.mp4' : ext, prefix: 'video' });
  }

  if (item.type === MessageItemType.VOICE && item.voice_item?.media?.encrypt_query_param && item.voice_item.media.aes_key) {
    const result = await downloadAndDecryptBuffer(item.voice_item.media.encrypt_query_param, item.voice_item.media.aes_key, cdnBaseUrl);
    return saveMediaBuffer({ accountId, buf: result.buf, ext: '.silk', prefix: 'voice' });
  }

  return null;
}

export async function extractInboundMediaPaths(params: {
  accountId: string;
  message: WeixinMessage;
  cdnBaseUrl: string;
}): Promise<string[]> {
  const mediaPaths: string[] = [];
  for (const item of params.message.item_list || []) {
    const localPath = await downloadMediaItem({
      accountId: params.accountId,
      item,
      cdnBaseUrl: params.cdnBaseUrl,
    }).catch(() => null);
    if (localPath) {
      mediaPaths.push(localPath);
    }
  }
  return mediaPaths;
}

function buildTextReq(params: {
  to: string;
  clientId: string;
  text: string;
  contextToken: string;
}): SendMessageReq {
  return {
    msg: {
      from_user_id: '',
      to_user_id: params.to,
      client_id: params.clientId,
      message_type: MessageType.BOT,
      message_state: MessageState.FINISH,
      context_token: params.contextToken,
      item_list: params.text ? [{ type: MessageItemType.TEXT, text_item: { text: params.text } }] : undefined,
    },
  };
}

async function sendSingleItem(params: {
  baseUrl: string;
  token?: string;
  to: string;
  contextToken: string;
  item: MessageItem;
  text?: string;
}): Promise<string> {
  let clientId = `lemonclaw-weixin-${randomUUID()}`;
  if (params.text?.trim()) {
    await sendMessage({
      baseUrl: params.baseUrl,
      token: params.token,
      body: buildTextReq({
        to: params.to,
        clientId,
        text: params.text,
        contextToken: params.contextToken,
      }),
    });
    clientId = `lemonclaw-weixin-${randomUUID()}`;
  }

  await sendMessage({
    baseUrl: params.baseUrl,
    token: params.token,
    body: {
      msg: {
        from_user_id: '',
        to_user_id: params.to,
        client_id: clientId,
        message_type: MessageType.BOT,
        message_state: MessageState.FINISH,
        context_token: params.contextToken,
        item_list: [params.item],
      },
    },
  });
  return clientId;
}

export async function sendWeixinMediaFiles(params: {
  accountId: string;
  to: string;
  text: string;
  mediaPaths: string[];
  contextToken: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
}): Promise<{ messageIds: string[] }> {
  const messageIds: string[] = [];
  let caption = params.text;
  for (const filePath of params.mediaPaths) {
    const mime = getOutboundMediaMime(filePath);
    if (mime.startsWith('image/')) {
      const uploaded = await uploadFileToWeixin({
        filePath,
        toUserId: params.to,
        baseUrl: params.baseUrl,
        token: params.token,
        cdnBaseUrl: params.cdnBaseUrl,
      });
      const messageId = await sendSingleItem({
        baseUrl: params.baseUrl,
        token: params.token,
        to: params.to,
        contextToken: params.contextToken,
        text: caption,
        item: {
          type: MessageItemType.IMAGE,
          image_item: {
            media: {
              encrypt_query_param: uploaded.downloadEncryptedQueryParam,
              aes_key: Buffer.from(uploaded.aeskey, 'hex').toString('base64'),
              encrypt_type: 1,
            },
          },
        },
      });
      messageIds.push(messageId);
      caption = '';
      continue;
    }

    if (mime.startsWith('video/')) {
      const uploaded = await uploadVideoToWeixin({
        filePath,
        toUserId: params.to,
        baseUrl: params.baseUrl,
        token: params.token,
        cdnBaseUrl: params.cdnBaseUrl,
      });
      const messageId = await sendSingleItem({
        baseUrl: params.baseUrl,
        token: params.token,
        to: params.to,
        contextToken: params.contextToken,
        text: caption,
        item: {
          type: MessageItemType.VIDEO,
          video_item: {
            media: {
              encrypt_query_param: uploaded.downloadEncryptedQueryParam,
              aes_key: Buffer.from(uploaded.aeskey, 'hex').toString('base64'),
              encrypt_type: 1,
            },
          },
        },
      });
      messageIds.push(messageId);
      caption = '';
      continue;
    }

    const uploaded = await uploadFileAttachmentToWeixin({
      filePath,
      toUserId: params.to,
      baseUrl: params.baseUrl,
      token: params.token,
      cdnBaseUrl: params.cdnBaseUrl,
    });
    const messageId = await sendSingleItem({
      baseUrl: params.baseUrl,
      token: params.token,
      to: params.to,
      contextToken: params.contextToken,
      text: caption,
      item: {
        type: MessageItemType.FILE,
        file_item: {
          file_name: path.basename(filePath),
          media: {
            encrypt_query_param: uploaded.downloadEncryptedQueryParam,
            aes_key: Buffer.from(uploaded.aeskey, 'hex').toString('base64'),
            encrypt_type: 1,
          },
        },
      },
    });
    messageIds.push(messageId);
    caption = '';
  }

  if (messageIds.length === 0 && params.text.trim()) {
    const textId = `lemonclaw-weixin-${randomUUID()}`;
    await sendMessage({
      baseUrl: params.baseUrl,
      token: params.token,
      body: buildTextReq({
        to: params.to,
        clientId: textId,
        text: params.text,
        contextToken: params.contextToken,
      }),
    });
    messageIds.push(textId);
  }

  return { messageIds };
}
