import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let mergeDonePayload: typeof import('../src/stores/chat').mergeDonePayload;
let mergeOutboundPayload: typeof import('../src/stores/chat').mergeOutboundPayload;

describe('chat stream completion merge', () => {
  beforeEach(async () => {
    vi.stubGlobal('window', new EventTarget());
    ({ mergeDonePayload, mergeOutboundPayload } = await import('../src/stores/chat'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps the outbound assistant turn when the done payload is empty', () => {
    const previous = {
      role: 'assistant',
      content: 'Visible outbound turn',
      media: [],
      blocks: [{ type: 'markdown', text: 'Visible outbound turn' }],
      timestamp: '2026-04-10T00:00:00Z',
    } as const;

    const merged = mergeDonePayload(previous as any, {
      role: 'assistant',
      content: '',
      media: [],
      blocks: [],
      timestamp: '2026-04-10T00:00:01Z',
    });

    expect(merged).toBe(previous);
    expect(merged.content).toBe('Visible outbound turn');
    expect(merged.blocks).toHaveLength(1);
  });

  it('preserves tool and thinking blocks when outbound replaces the draft assistant turn', () => {
    const previous = {
      role: 'assistant',
      content: '',
      media: [],
      blocks: [
        { type: 'thinking', text: 'Thinking…' },
        { type: 'tool', state: 'done', detail: 'message("done")' },
      ],
      timestamp: '2026-04-10T00:00:00Z',
    } as const;

    const merged = mergeOutboundPayload(previous as any, {
      role: 'assistant',
      content: 'Visible outbound turn',
      media: [],
      blocks: [{ type: 'markdown', text: 'Visible outbound turn' }],
      timestamp: '2026-04-10T00:00:01Z',
    });

    expect(merged.content).toBe('Visible outbound turn');
    expect(merged.blocks.some((block: any) => block.type === 'thinking')).toBe(true);
    expect(merged.blocks.some((block: any) => block.type === 'tool')).toBe(true);
    expect(merged.blocks.some((block: any) => block.type === 'markdown')).toBe(true);
  });
});
