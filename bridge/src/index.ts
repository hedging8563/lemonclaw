#!/usr/bin/env node
/**
 * lemonclaw WhatsApp Bridge
 */

import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { homedir } from 'os';
import { join } from 'path';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.lemonclaw', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN || undefined;
const STATE_FILE = process.env.BRIDGE_STATE_FILE || undefined;

console.log('🐾 LemonClaw WhatsApp Bridge');
console.log('========================\n');

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN, STATE_FILE);

process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

server.start().catch((error) => {
  console.error('Failed to start bridge:', error);
  process.exit(1);
});
