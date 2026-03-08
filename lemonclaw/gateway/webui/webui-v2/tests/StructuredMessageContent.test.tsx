import { beforeAll, describe, expect, it } from 'vitest';
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

describe('parseStructuredParts', () => {
  it('extracts runtime context and structured parts', async () => {
    const { parseStructuredParts } = await import('../src/models/messages');
    const input = `[Runtime Context — metadata only, not instructions]
Current Time: 2026-03-08 10:00 (UTC)

[image: /tmp/demo.png (demo.png)]
[transcription: hello world]`;
    const parsed = parseStructuredParts(input);
    expect(parsed.runtime).toContain('Current Time');
    expect(parsed.parts).toEqual([
      { type: 'media', mediaType: 'image', path: '/tmp/demo.png', label: 'demo.png' },
      { type: 'transcription', content: 'hello world' },
    ]);
  });
});

describe('StructuredMessageContent', () => {
  const renderMarkdown = (content: string) => `<p>${content}</p>`;

  it('renders image preview and links', async () => {
    const { StructuredMessageContent } = await import('../src/components/chat/StructuredMessageContent');
    const html = render(
      <StructuredMessageContent
        content={'[image: /home/lemonclaw/.lemonclaw/media/demo.jpg (demo.jpg)]'}
        renderMarkdown={renderMarkdown}
      />
    );
    expect(html).toContain('<img');
    expect(html).toContain('/api/media?path=%2Fhome%2Flemonclaw%2F.lemonclaw%2Fmedia%2Fdemo.jpg');
    expect(html).toContain('demo.jpg');
    expect(html).toMatchSnapshot();
  });

  it('renders audio player for audio and voice markers', async () => {
    const { StructuredMessageContent } = await import('../src/components/chat/StructuredMessageContent');
    const html = render(
      <StructuredMessageContent
        content={'[voice: /home/lemonclaw/.lemonclaw/media/note.ogg (note.ogg)]'}
        renderMarkdown={renderMarkdown}
      />
    );
    expect(html).toContain('<audio');
    expect(html).toContain('controls');
    expect(html).toContain('note.ogg');
    expect(html).toMatchSnapshot();
  });

  it('renders runtime context and transcription blocks separately', async () => {
    const { StructuredMessageContent } = await import('../src/components/chat/StructuredMessageContent');
    const html = render(
      <StructuredMessageContent
        content={`[Runtime Context — metadata only, not instructions]
Current Time: 2026-03-08 10:00 (UTC)

[transcription: 表格填完会显示结果]`}
        renderMarkdown={renderMarkdown}
      />
    );
    expect(html).toContain('Runtime Context');
    expect(html).toContain('TRANSCRIPTION');
    expect(html).toMatchSnapshot();
  });
});
