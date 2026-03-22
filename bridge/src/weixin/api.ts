export interface WeixinQrStartResponse {
  qrcode: string;
  qrcode_img_content: string;
}

export interface WeixinQrStatusResponse {
  status: 'wait' | 'scaned' | 'confirmed' | 'expired';
  bot_token?: string;
  ilink_bot_id?: string;
  baseurl?: string;
  ilink_user_id?: string;
}

export interface TextItem {
  text?: string;
}

export interface VoiceItem {
  media?: CDNMedia;
  encode_type?: number;
  bits_per_sample?: number;
  sample_rate?: number;
  playtime?: number;
  text?: string;
}

export interface CDNMedia {
  encrypt_query_param?: string;
  aes_key?: string;
  encrypt_type?: number;
}

export interface ImageItem {
  media?: CDNMedia;
  aeskey?: string;
}

export interface FileItem {
  media?: CDNMedia;
  file_name?: string;
  md5?: string;
  len?: string;
}

export interface VideoItem {
  media?: CDNMedia;
}

export interface MessageItem {
  type?: number;
  text_item?: TextItem;
  image_item?: ImageItem;
  voice_item?: VoiceItem;
  file_item?: FileItem;
  video_item?: VideoItem;
}

export interface WeixinMessage {
  seq?: number;
  message_id?: number;
  from_user_id?: string;
  to_user_id?: string;
  client_id?: string;
  create_time_ms?: number;
  update_time_ms?: number;
  delete_time_ms?: number;
  session_id?: string;
  group_id?: string;
  message_type?: number;
  message_state?: number;
  item_list?: MessageItem[];
  context_token?: string;
}

export interface GetUpdatesResp {
  ret?: number;
  errcode?: number;
  errmsg?: string;
  msgs?: WeixinMessage[];
  get_updates_buf?: string;
  longpolling_timeout_ms?: number;
}

export interface SendMessageReq {
  msg?: WeixinMessage;
}

export interface GetUploadUrlResp {
  upload_param?: string;
  thumb_upload_param?: string;
}

export const UploadMediaType = {
  IMAGE: 1,
  VIDEO: 2,
  FILE: 3,
  VOICE: 4,
} as const;

export const MessageItemType = {
  NONE: 0,
  TEXT: 1,
  IMAGE: 2,
  VOICE: 3,
  FILE: 4,
  VIDEO: 5,
} as const;

export const MessageType = {
  NONE: 0,
  USER: 1,
  BOT: 2,
} as const;

export const MessageState = {
  NEW: 0,
  GENERATING: 1,
  FINISH: 2,
} as const;

const DEFAULT_BOT_TYPE = '3';
const QR_LONG_POLL_TIMEOUT_MS = 35_000;
const DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000;
const DEFAULT_API_TIMEOUT_MS = 15_000;
const CLIENT_VERSION_HEADER = '1';

function ensureTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`;
}

async function jsonFetch<T>(url: string, options: RequestInit = {}, timeoutMs = DEFAULT_API_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ''}`);
    }
    return await response.json() as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function apiPost<T>(
  baseUrl: string,
  endpoint: string,
  payload: Record<string, unknown>,
  token?: string,
  timeoutMs = DEFAULT_API_TIMEOUT_MS,
): Promise<T> {
  const url = new URL(endpoint, ensureTrailingSlash(baseUrl));
  const randomWechatUin = Buffer.from(String(Math.floor(Math.random() * 0xffffffff)), 'utf-8').toString('base64');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    AuthorizationType: 'ilink_bot_token',
    'X-WECHAT-UIN': randomWechatUin,
  };
  if (token?.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return jsonFetch<T>(
    url.toString(),
    {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    },
    timeoutMs,
  );
}

export async function fetchWeixinQRCode(baseUrl: string, botType = DEFAULT_BOT_TYPE): Promise<WeixinQrStartResponse> {
  const url = new URL(`ilink/bot/get_bot_qrcode?bot_type=${encodeURIComponent(botType)}`, ensureTrailingSlash(baseUrl));
  return jsonFetch<WeixinQrStartResponse>(url.toString());
}

export async function pollWeixinQRStatus(baseUrl: string, qrcode: string): Promise<WeixinQrStatusResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), QR_LONG_POLL_TIMEOUT_MS);
  try {
    const url = new URL(`ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcode)}`, ensureTrailingSlash(baseUrl));
    const response = await fetch(url.toString(), {
      headers: { 'iLink-App-ClientVersion': CLIENT_VERSION_HEADER },
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ''}`);
    }
    return await response.json() as WeixinQrStatusResponse;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { status: 'wait' };
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function getUpdates(params: {
  baseUrl: string;
  token?: string;
  getUpdatesBuf?: string;
  timeoutMs?: number;
}): Promise<GetUpdatesResp> {
  try {
    return await apiPost<GetUpdatesResp>(
      params.baseUrl,
      'ilink/bot/getupdates',
      {
        get_updates_buf: params.getUpdatesBuf ?? '',
        base_info: { channel_version: 'lemonclaw-weixin-bridge' },
      },
      params.token,
      params.timeoutMs ?? DEFAULT_LONG_POLL_TIMEOUT_MS,
    );
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { ret: 0, msgs: [], get_updates_buf: params.getUpdatesBuf ?? '' };
    }
    throw error;
  }
}

export async function sendMessage(params: {
  baseUrl: string;
  token?: string;
  body: SendMessageReq;
  timeoutMs?: number;
}): Promise<void> {
  await apiPost<Record<string, unknown>>(
    params.baseUrl,
    'ilink/bot/sendmessage',
    {
      ...params.body,
      base_info: { channel_version: 'lemonclaw-weixin-bridge' },
    },
    params.token,
    params.timeoutMs ?? DEFAULT_API_TIMEOUT_MS,
  );
}

export async function getUploadUrl(params: {
  baseUrl: string;
  token?: string;
  filekey?: string;
  mediaType?: number;
  toUserId?: string;
  rawsize?: number;
  rawfilemd5?: string;
  filesize?: number;
  thumbRawsize?: number;
  thumbRawfilemd5?: string;
  thumbFilesize?: number;
  noNeedThumb?: boolean;
  aeskey?: string;
  timeoutMs?: number;
}): Promise<GetUploadUrlResp> {
  return apiPost<GetUploadUrlResp>(
    params.baseUrl,
    'ilink/bot/getuploadurl',
    {
      filekey: params.filekey,
      media_type: params.mediaType,
      to_user_id: params.toUserId,
      rawsize: params.rawsize,
      rawfilemd5: params.rawfilemd5,
      filesize: params.filesize,
      thumb_rawsize: params.thumbRawsize,
      thumb_rawfilemd5: params.thumbRawfilemd5,
      thumb_filesize: params.thumbFilesize,
      no_need_thumb: params.noNeedThumb,
      aeskey: params.aeskey,
      base_info: { channel_version: 'lemonclaw-weixin-bridge' },
    },
    params.token,
    params.timeoutMs ?? DEFAULT_API_TIMEOUT_MS,
  );
}
