import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { h } from 'preact';
import render from 'preact-render-to-string';

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    },
    configurable: true,
  });
});

describe('MessageList', () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.doMock('dompurify', () => ({
      default: {
        sanitize: (value: string) => value,
        addHook: () => undefined,
      },
    }));
    const chat = await import('../src/stores/chat');
    const sessions = await import('../src/stores/sessions');
    chat.messages.value = [];
    chat.isLoadingHistory.value = false;
    chat.isStreaming.value = false;
    sessions.activeSessionKey.value = 'webui:test';
  });

  it('renders assistant media attachments from media[] history', async () => {
    const chat = await import('../src/stores/chat');
    const { MessageList } = await import('../src/components/chat/MessageList');
    const { normalizeMessage } = await import('../src/models/messages');
    chat.messages.value = [
      normalizeMessage({
        role: 'assistant',
        content: '附件如下',
        media: ['/home/lemonclaw/.lemonclaw/media/demo.jpg', '/home/lemonclaw/.lemonclaw/media/note.ogg'],
      }),
    ];
    const html = render(<MessageList />);
    expect(html).toContain('<img');
    expect(html).toContain('<audio');
    expect(html).toContain('/api/media?path=%2Fhome%2Flemonclaw%2F.lemonclaw%2Fmedia%2Fdemo.jpg');
    expect(html).toContain('/api/media?path=%2Fhome%2Flemonclaw%2F.lemonclaw%2Fmedia%2Fnote.ogg');
    expect(html).toMatchSnapshot();
  });
});
