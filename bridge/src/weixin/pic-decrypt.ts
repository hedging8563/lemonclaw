import { decryptAesEcb } from './aes-ecb.js';
import { buildCdnDownloadUrl } from './cdn-url.js';

async function fetchCdnBytes(url: string): Promise<{ buf: Buffer; contentType: string | null }> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`CDN download ${response.status} ${response.statusText}${body ? `: ${body}` : ''}`);
  }
  return {
    buf: Buffer.from(await response.arrayBuffer()),
    contentType: response.headers.get('content-type'),
  };
}

function parseAesKey(aesKeyBase64: string): Buffer {
  const decoded = Buffer.from(aesKeyBase64, 'base64');
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
