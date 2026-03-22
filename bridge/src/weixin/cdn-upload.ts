import { encryptAesEcb } from './aes-ecb.js';
import { buildCdnUploadUrl } from './cdn-url.js';

const UPLOAD_MAX_RETRIES = 3;

export async function uploadBufferToCdn(params: {
  buf: Buffer;
  uploadParam: string;
  filekey: string;
  cdnBaseUrl: string;
  aeskey: Buffer;
  timeoutMs?: number;
}): Promise<{ downloadParam: string }> {
  const ciphertext = encryptAesEcb(params.buf, params.aeskey);
  const cdnUrl = buildCdnUploadUrl({
    cdnBaseUrl: params.cdnBaseUrl,
    uploadParam: params.uploadParam,
    filekey: params.filekey,
  });

  let lastError: unknown;
  for (let attempt = 1; attempt <= UPLOAD_MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timeoutMs = Math.max(1_000, Math.floor(params.timeoutMs ?? 60_000));
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(cdnUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: new Uint8Array(ciphertext),
        signal: controller.signal,
      });
      if (response.status >= 400 && response.status < 500) {
        const errMsg = response.headers.get('x-error-message') ?? (await response.text());
        throw new Error(`CDN upload client error ${response.status}: ${errMsg}`);
      }
      if (response.status !== 200) {
        const errMsg = response.headers.get('x-error-message') ?? `status ${response.status}`;
        throw new Error(`CDN upload server error: ${errMsg}`);
      }
      const downloadParam = response.headers.get('x-encrypted-param') ?? undefined;
      if (!downloadParam) {
        throw new Error('CDN upload response missing x-encrypted-param header');
      }
      return { downloadParam };
    } catch (error) {
      lastError = error instanceof Error && error.name === 'AbortError'
        ? new Error(`CDN upload timed out after ${timeoutMs}ms`)
        : error;
      if (error instanceof Error && error.message.includes('client error')) {
        throw error;
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }

  throw lastError instanceof Error ? lastError : new Error('CDN upload failed');
}
