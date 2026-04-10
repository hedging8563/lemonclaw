import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { wsConnect } from '../src/api/client';

class MockWebSocket {
  static OPEN = 1;

  public readyState = 0;
  public onopen: (() => void) | null = null;
  public onmessage: ((event: { data: string }) => void) | null = null;
  public onclose: (() => void) | null = null;
  public onerror: (() => void) | null = null;

  constructor(public url: string) {
    instances.push(this);
  }

  send = vi.fn();

  close = vi.fn(() => {
    this.readyState = 3;
    this.onclose?.();
  });
}

const instances: MockWebSocket[] = [];

describe('wsConnect', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    instances.length = 0;
    vi.stubGlobal('window', {
      location: {
        protocol: 'https:',
        host: 'example.test',
      },
    });
    vi.stubGlobal('WebSocket', MockWebSocket as any);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('suppresses reconnects while auth is unavailable', async () => {
    const onMessage = vi.fn();
    const onStatusChange = vi.fn();

    wsConnect('/ws/session?session_key=telegram%3A123', onMessage, onStatusChange, {
      shouldReconnect: () => false,
    });

    expect(instances).toHaveLength(1);
    instances[0].onclose?.();

    await vi.advanceTimersByTimeAsync(1500);

    expect(instances).toHaveLength(1);
    expect(onStatusChange).toHaveBeenCalledWith(false);
  });
});
