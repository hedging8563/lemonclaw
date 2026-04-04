import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';

import { aesEcbPaddedSize } from './aes-ecb.js';
import { getUploadUrl, UploadMediaType } from './api.js';
import { uploadBufferToCdn } from './cdn-upload.js';
import { getMimeFromFilename } from './mime.js';
import { WEIXIN_MEDIA_MAX_BYTES } from './limits.js';

const CDN_UPLOAD_TIMEOUT_FLOOR_MS = 20_000;
const CDN_UPLOAD_TIMEOUT_HEADROOM_MS = 30_000;
const CDN_UPLOAD_TIMEOUT_MAX_MS = 15 * 60_000;
const CDN_UPLOAD_MIN_BYTES_PER_SECOND = 20 * 1024;

export interface UploadedFileInfo {
  filekey: string;
  downloadEncryptedQueryParam: string;
  aeskey: string;
  fileSize: number;
  fileSizeCiphertext: number;
}

export function estimateCdnUploadTimeoutMs(fileSizeBytes: number): number {
  const safeBytes = Number.isFinite(fileSizeBytes) ? Math.max(0, fileSizeBytes) : 0;
  if (safeBytes <= 0) {
    return CDN_UPLOAD_TIMEOUT_FLOOR_MS;
  }

  const estimatedMs = CDN_UPLOAD_TIMEOUT_HEADROOM_MS
    + Math.ceil((safeBytes / CDN_UPLOAD_MIN_BYTES_PER_SECOND) * 1000);
  return Math.max(
    CDN_UPLOAD_TIMEOUT_FLOOR_MS,
    Math.min(CDN_UPLOAD_TIMEOUT_MAX_MS, estimatedMs),
  );
}

async function uploadMediaToCdn(params: {
  filePath: string;
  toUserId: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
  mediaType: number;
}): Promise<UploadedFileInfo> {
  const fileStat = await fs.stat(params.filePath);
  if (fileStat.size <= 0) {
    throw new Error(`Weixin media cannot be empty: ${params.filePath}`);
  }
  if (fileStat.size > WEIXIN_MEDIA_MAX_BYTES) {
    throw new Error(`Weixin media too large: ${fileStat.size} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
  }
  const plaintext = await fs.readFile(params.filePath);
  const rawsize = plaintext.length;
  const rawfilemd5 = crypto.createHash('md5').update(plaintext).digest('hex');
  const filesize = aesEcbPaddedSize(rawsize);
  const uploadTimeoutMs = estimateCdnUploadTimeoutMs(rawsize);
  const filekey = crypto.randomBytes(16).toString('hex');
  const aeskey = crypto.randomBytes(16);

  const uploadUrlResp = await getUploadUrl({
    baseUrl: params.baseUrl,
    token: params.token,
    filekey,
    mediaType: params.mediaType,
    toUserId: params.toUserId,
    rawsize,
    rawfilemd5,
    filesize,
    noNeedThumb: true,
    aeskey: aeskey.toString('hex'),
  });

  const uploadFullUrl = uploadUrlResp.upload_full_url?.trim() || undefined;
  const uploadParam = uploadUrlResp.upload_param || undefined;
  if (!uploadFullUrl && !uploadParam) {
    throw new Error(`getUploadUrl returned no upload URL: ${JSON.stringify(uploadUrlResp)}`);
  }

  const { downloadParam } = await uploadBufferToCdn({
    buf: plaintext,
    uploadFullUrl,
    uploadParam,
    filekey: uploadParam ? filekey : undefined,
    cdnBaseUrl: uploadParam ? params.cdnBaseUrl : undefined,
    aeskey,
    timeoutMs: uploadTimeoutMs,
  });

  return {
    filekey,
    downloadEncryptedQueryParam: downloadParam,
    aeskey: aeskey.toString('hex'),
    fileSize: rawsize,
    fileSizeCiphertext: filesize,
  };
}

export async function uploadFileToWeixin(params: {
  filePath: string;
  toUserId: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
}): Promise<UploadedFileInfo> {
  return uploadMediaToCdn({ ...params, mediaType: UploadMediaType.IMAGE });
}

export async function uploadVideoToWeixin(params: {
  filePath: string;
  toUserId: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
}): Promise<UploadedFileInfo> {
  return uploadMediaToCdn({ ...params, mediaType: UploadMediaType.VIDEO });
}

export async function uploadVoiceToWeixin(params: {
  filePath: string;
  toUserId: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
}): Promise<UploadedFileInfo> {
  return uploadMediaToCdn({ ...params, mediaType: UploadMediaType.VOICE });
}

export async function uploadFileAttachmentToWeixin(params: {
  filePath: string;
  toUserId: string;
  baseUrl: string;
  token?: string;
  cdnBaseUrl: string;
}): Promise<UploadedFileInfo> {
  return uploadMediaToCdn({ ...params, mediaType: UploadMediaType.FILE });
}

export function getOutboundMediaMime(filePath: string): string {
  return getMimeFromFilename(path.basename(filePath));
}
