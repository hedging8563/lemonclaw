import { decryptAesEcb } from './aes-ecb.js';
import { buildCdnDownloadUrl } from './cdn-url.js';
import { WEIXIN_MEDIA_MAX_BYTES } from './limits.js';

async function fetchCdnBytes(url: string): Promise<{ buf: Buffer; contentType: string | null }> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`CDN download ${response.status} ${response.statusText}${body ? `: ${body}` : ''}`);
  }
  const declaredLength = Number(response.headers.get('content-length') || '0');
  if (Number.isFinite(declaredLength) && declaredLength > WEIXIN_MEDIA_MAX_BYTES) {
    throw new Error(`CDN media too large: ${declaredLength} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const fallback = Buffer.from(await response.arrayBuffer());
    if (fallback.length > WEIXIN_MEDIA_MAX_BYTES) {
      throw new Error(`CDN media too large: ${fallback.length} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
    }
    return {
      buf: fallback,
      contentType: response.headers.get('content-type'),
    };
  }
  const chunks: Buffer[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = Buffer.from(value);
    total += chunk.length;
    if (total > WEIXIN_MEDIA_MAX_BYTES) {
      throw new Error(`CDN media too large: ${total} bytes exceeds ${WEIXIN_MEDIA_MAX_BYTES}`);
    }
    chunks.push(chunk);
  }
  return {
    buf: Buffer.concat(chunks, total),
    contentType: response.headers.get('content-type'),
  };
}

export function parseAesKey(aesKeyValue: string): Buffer {
  const trimmed = String(aesKeyValue || '').trim();
  if (/^[0-9a-fA-F]{32}$/.test(trimmed)) {
    return Buffer.from(trimmed, 'hex');
  }

  const decoded = Buffer.from(trimmed, 'base64');
  if (decoded.length === 16) {
    return decoded;
  }
  if (decoded.length === 32 && /^[0-9a-fA-F]{32}$/.test(decoded.toString('ascii'))) {
    return Buffer.from(decoded.toString('ascii'), 'hex');
  }
  throw new Error(`Unsupported aes_key payload length ${decoded.length}`);
}

export async function downloadAndDecryptBuffer(
  encryptedQueryParam: string,
  aesKeyBase64: string,
  cdnBaseUrl: string,
): Promise<{ buf: Buffer; contentType: string | null }> {
  const key = parseAesKey(aesKeyBase64);
  const url = buildCdnDownloadUrl(encryptedQueryParam, cdnBaseUrl);
  const encrypted = await fetchCdnBytes(url);
  return {
    buf: decryptAesEcb(encrypted.buf, key),
    contentType: encrypted.contentType,
  };
}

export async function downloadPlainCdnBuffer(
  encryptedQueryParam: string,
  cdnBaseUrl: string,
): Promise<{ buf: Buffer; contentType: string | null }> {
  const url = buildCdnDownloadUrl(encryptedQueryParam, cdnBaseUrl);
  return fetchCdnBytes(url);
}
