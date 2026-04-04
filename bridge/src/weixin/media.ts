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
import { silkToWav } from './silk-transcode.js';
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

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function itemTypeDebugLabel(item: MessageItem): string {
  switch (item.type) {
    case MessageItemType.IMAGE:
      return 'image';
    case MessageItemType.FILE:
      return 'file';
    case MessageItemType.VIDEO:
      return 'video';
    case MessageItemType.VOICE:
      return 'voice';
    case MessageItemType.TEXT:
      return 'text';
    default:
      return `unknown(${String(item.type ?? 'n/a')})`;
  }
}

async function downloadInboundBuffer(params: {
  encryptedQueryParam?: string;
  aesKey?: string;
  cdnBaseUrl: string;
}): Promise<{ buf: Buffer; contentType: string | null } | null> {
  if (!params.encryptedQueryParam) {
    return null;
  }
  if (params.aesKey?.trim()) {
    return downloadAndDecryptBuffer(params.encryptedQueryParam, params.aesKey, params.cdnBaseUrl);
  }
  return downloadPlainCdnBuffer(params.encryptedQueryParam, params.cdnBaseUrl);
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

  if (item.type === MessageItemType.FILE && item.file_item?.media?.encrypt_query_param) {
    const result = await downloadInboundBuffer({
      encryptedQueryParam: item.file_item.media.encrypt_query_param,
      aesKey: item.file_item.media.aes_key || item.file_item.aeskey,
      cdnBaseUrl,
    });
    if (result) {
      const ext = path.extname(item.file_item.file_name || '') || getExtensionFromContentTypeOrUrl(result.contentType, 'https://example.local/file.bin');
      return saveMediaBuffer({ accountId, buf: result.buf, ext: ext || '.bin', prefix: 'file' });
    }
  }

  if (item.type === MessageItemType.VIDEO && item.video_item) {
    const videoItem = item.video_item;
    try {
      const result = await downloadInboundBuffer({
        encryptedQueryParam: videoItem.media?.encrypt_query_param,
        aesKey: videoItem.media?.aes_key || videoItem.aeskey,
        cdnBaseUrl,
      });
      if (result) {
        const ext = getExtensionFromContentTypeOrUrl(result.contentType, 'https://example.local/video.mp4');
        return saveMediaBuffer({ accountId, buf: result.buf, ext: ext === '.bin' ? '.mp4' : ext, prefix: 'video' });
      }
    } catch (error) {
      console.warn(`[weixin] inbound video download failed, trying thumbnail fallback: ${formatError(error)}`);
    }

    try {
      const thumb = await downloadInboundBuffer({
        encryptedQueryParam: videoItem.thumb_media?.encrypt_query_param,
        aesKey: videoItem.thumb_media?.aes_key || videoItem.thumb_aeskey,
        cdnBaseUrl,
      });
      if (thumb) {
        const ext = getExtensionFromContentTypeOrUrl(thumb.contentType, 'https://example.local/video-thumb.jpg');
        console.warn('[weixin] inbound video main media unavailable, using thumbnail fallback');
        return saveMediaBuffer({ accountId, buf: thumb.buf, ext: ext === '.bin' ? '.jpg' : ext, prefix: 'image' });
      }
    } catch (error) {
      console.warn(`[weixin] inbound video thumbnail download failed: ${formatError(error)}`);
    }

    console.warn('[weixin] inbound video message had no downloadable media payload');
    return null;
  }

  if (item.type === MessageItemType.VOICE && item.voice_item?.media?.encrypt_query_param) {
    const result = await downloadInboundBuffer({
      encryptedQueryParam: item.voice_item.media.encrypt_query_param,
      aesKey: item.voice_item.media.aes_key || item.voice_item.aeskey,
      cdnBaseUrl,
    });
    if (result) {
      const wav = await silkToWav(result.buf);
      if (wav) {
        return saveMediaBuffer({ accountId, buf: wav, ext: '.wav', prefix: 'voice' });
      }
      return saveMediaBuffer({ accountId, buf: result.buf, ext: '.silk', prefix: 'voice' });
    }
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
    }).catch((error) => {
      console.warn(`[weixin] failed to process inbound ${itemTypeDebugLabel(item)} item: ${formatError(error)}`);
      return null;
    });
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

function buildFileMessageItem(
  filePath: string,
  downloadEncryptedQueryParam: string,
  aeskeyHex: string,
  fileSize: number,
): MessageItem {
  return {
    type: MessageItemType.FILE,
    file_item: {
      file_name: path.basename(filePath),
      len: String(fileSize),
      media: {
        encrypt_query_param: downloadEncryptedQueryParam,
        aes_key: encodeAesKeyHexToBase64(aeskeyHex),
        encrypt_type: 1,
      },
    },
  };
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
  let caption = params.text.trim();
  for (const filePath of params.mediaPaths) {
    const mime = getOutboundMediaMime(filePath);
    if (mime.startsWith('audio/')) {
      // Official openclaw-weixin does not implement outbound voice_item sending.
      // Route outbound audio through the file attachment path so the client
      // reliably renders a downloadable asset instead of an empty voice bubble.
      console.info(`[weixin] uploading audio as file attachment ${path.basename(filePath)} -> ${params.to}`);
      const uploaded = await uploadFileAttachmentToWeixin({
        filePath,
        toUserId: params.to,
        baseUrl: params.baseUrl,
        token: params.token,
        cdnBaseUrl: params.cdnBaseUrl,
      });
      const item = buildFileMessageItem(
        filePath,
        uploaded.downloadEncryptedQueryParam,
        uploaded.aeskey,
        uploaded.fileSize,
      );
      console.info(`[weixin] sending audio/file attachment ${path.basename(filePath)} -> ${params.to}`);
      const messageId = await sendSingleItem({
        baseUrl: params.baseUrl,
        token: params.token,
        to: params.to,
        contextToken: params.contextToken,
        text: caption,
        item,
      });
      messageIds.push(messageId);
      caption = '';
      continue;
    }

    if (mime.startsWith('image/')) {
      console.info(`[weixin] uploading image attachment ${path.basename(filePath)} -> ${params.to}`);
      const uploaded = await uploadFileToWeixin({
        filePath,
        toUserId: params.to,
        baseUrl: params.baseUrl,
        token: params.token,
        cdnBaseUrl: params.cdnBaseUrl,
      });
      console.info(`[weixin] sending image attachment ${path.basename(filePath)} -> ${params.to}`);
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
              aes_key: encodeAesKeyHexToBase64(uploaded.aeskey),
              encrypt_type: 1,
            },
            mid_size: uploaded.fileSizeCiphertext,
          },
        },
      });
      messageIds.push(messageId);
      caption = '';
      continue;
    }

    if (mime.startsWith('video/')) {
      console.info(`[weixin] uploading video attachment ${path.basename(filePath)} -> ${params.to}`);
      const uploaded = await uploadVideoToWeixin({
        filePath,
        toUserId: params.to,
        baseUrl: params.baseUrl,
        token: params.token,
        cdnBaseUrl: params.cdnBaseUrl,
      });
      console.info(`[weixin] sending video attachment ${path.basename(filePath)} -> ${params.to}`);
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
              aes_key: encodeAesKeyHexToBase64(uploaded.aeskey),
              encrypt_type: 1,
            },
            video_size: uploaded.fileSizeCiphertext,
          },
        },
      });
      messageIds.push(messageId);
      caption = '';
      continue;
    }

    console.info(`[weixin] uploading file attachment ${path.basename(filePath)} -> ${params.to}`);
    const uploaded = await uploadFileAttachmentToWeixin({
      filePath,
      toUserId: params.to,
      baseUrl: params.baseUrl,
      token: params.token,
      cdnBaseUrl: params.cdnBaseUrl,
    });
    console.info(`[weixin] sending file attachment ${path.basename(filePath)} -> ${params.to}`);
    const messageId = await sendSingleItem({
      baseUrl: params.baseUrl,
      token: params.token,
      to: params.to,
      contextToken: params.contextToken,
      text: caption,
      item: buildFileMessageItem(
        filePath,
        uploaded.downloadEncryptedQueryParam,
        uploaded.aeskey,
        uploaded.fileSize,
      ),
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
