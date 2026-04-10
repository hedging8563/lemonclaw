import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'fs';
import { dirname } from 'path';

import { eventQueueFilePath } from './accounts.js';
import type { WeixinBridgeEvent } from './monitor.js';

interface PersistedQueue {
  nextId: number;
  events: WeixinBridgeEvent[];
}

function defaultState(): PersistedQueue {
  return { nextId: 1, events: [] };
}

function backupFile(file: string): string {
  return `${file}.bak`;
}

function tryLoadState(file: string): PersistedQueue | null {
  try {
    const raw = JSON.parse(readFileSync(file, 'utf-8')) as Partial<PersistedQueue>;
    return {
      nextId: Math.max(1, Number(raw.nextId) || 1),
      events: Array.isArray(raw.events) ? raw.events as WeixinBridgeEvent[] : [],
    };
  } catch {
    return null;
  }
}

function loadState(): PersistedQueue {
  const file = eventQueueFilePath();
  return tryLoadState(file)
    || tryLoadState(backupFile(file))
    || defaultState();
}

function saveState(state: PersistedQueue): void {
  const file = eventQueueFilePath();
  mkdirSync(dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(state, null, 2));
  if (existsSync(file)) {
    copyFileSync(file, backupFile(file));
  }
  renameSync(tmp, file);
}

export class PersistentWeixinEventQueue {
  private state: PersistedQueue = loadState();

  enqueue(event: Omit<WeixinBridgeEvent, 'id'>): WeixinBridgeEvent {
    const next: WeixinBridgeEvent = { ...event, id: this.state.nextId++ };
    this.state.events.push(next);
    saveState(this.state);
    return next;
  }

  ackThrough(cursor: number): void {
    const safeCursor = Math.max(0, Number(cursor) || 0);
    if (safeCursor <= 0) return;
    const filtered = this.state.events.filter((event) => event.id > safeCursor);
    if (filtered.length === this.state.events.length) return;
    this.state.events = filtered;
    saveState(this.state);
  }

  listAfter(cursor: number, limit: number): WeixinBridgeEvent[] {
    const safeCursor = Math.max(0, Number(cursor) || 0);
    const safeLimit = Math.max(1, Math.min(Number(limit) || 50, 500));
    return this.state.events.filter((event) => event.id > safeCursor).slice(0, safeLimit);
  }

  lastId(): number {
    return this.state.events.length > 0 ? this.state.events[this.state.events.length - 1].id : 0;
  }

  size(): number {
    return this.state.events.length;
  }
}
