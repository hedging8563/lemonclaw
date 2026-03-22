#!/usr/bin/env node

import { WeixinBridgeServer } from './server.js';
import { DEFAULT_WEIXIN_BASE_URL, DEFAULT_WEIXIN_CDN_BASE_URL } from './accounts.js';

const port = parseInt(process.env.WEIXIN_BRIDGE_PORT || '3002', 10);
const token = process.env.WEIXIN_BRIDGE_TOKEN || undefined;
const baseUrl = process.env.WEIXIN_BASE_URL || DEFAULT_WEIXIN_BASE_URL;
const cdnBaseUrl = process.env.WEIXIN_CDN_BASE_URL || DEFAULT_WEIXIN_CDN_BASE_URL;

const server = new WeixinBridgeServer(port, baseUrl, cdnBaseUrl, token);

process.on('SIGINT', async () => {
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

server.start().catch((error) => {
  console.error('Failed to start Weixin bridge:', error);
  process.exit(1);
});
