import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';

import { aesEcbPaddedSize } from './aes-ecb.js';
import { getUploadUrl, UploadMediaType } from './api.js';
import { uploadBufferToCdn } from './cdn-upload.js';
import { getMimeFromFilename } from './mime.js';
import { WEIXIN_MEDIA_MAX_BYTES } from './limits.js';

export interface UploadedFileInfo {
  filekey: string;
  downloadEncryptedQueryParam: string;
  aeskey: string;
  fileSize: number;
  fileSizeCiphertext: number;
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
  if (fileStat.size > WEIXIN_MEDIA_MAX_BYTES) {
    throw new Error(`Weixin media too large: ${fileStat.size} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
  }
  const plaintext = await fs.readFile(params.filePath);
  const rawsize = plaintext.length;
  const rawfilemd5 = crypto.createHash('md5').update(plaintext).digest('hex');
  const filesize = aesEcbPaddedSize(rawsize);
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

  if (!uploadUrlResp.upload_param) {
    throw new Error('getUploadUrl returned no upload_param');
  }

  const { downloadParam } = await uploadBufferToCdn({
    buf: plaintext,
    uploadParam: uploadUrlResp.upload_param,
    filekey,
    cdnBaseUrl: params.cdnBaseUrl,
    aeskey,
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
