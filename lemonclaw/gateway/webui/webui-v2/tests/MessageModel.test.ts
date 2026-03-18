import { describe, expect, it } from 'vitest';

import { normalizeMessage, startToolBlock, type UIMessage } from '../src/models/messages';

describe('message models', () => {
  it('suppresses draft markdown for assistant tool-call messages', () => {
    const message = normalizeMessage({
      role: 'assistant',
      content: '我先检查一下文件。',
      tool_calls: [
        {
          id: 'call_1',
          state: 'done',
          detail: 'read_file("notes.md")',
        },
      ],
    });

    expect(message.blocks.some((block) => block.type === 'markdown')).toBe(false);
    expect(message.blocks.some((block) => block.type === 'tool')).toBe(true);
  });

  it('clears transient draft text when a tool run starts', () => {
    const draftMessage: UIMessage = {
      role: 'assistant',
      content: '我先检查一下文件。',
      media: [],
      blocks: [{ type: 'markdown', text: '我先检查一下文件。' }],
    };

    const next = startToolBlock(draftMessage, 'read_file("notes.md")');

    expect(next.content).toBe('');
    expect(next.blocks.some((block) => block.type === 'markdown')).toBe(false);
    expect(next.blocks.some((block) => block.type === 'tool' && block.state === 'running')).toBe(true);
  });
});
