import assert from 'node:assert/strict';
import test from 'node:test';

import { filterWeixinMarkdown } from './markdown-filter.js';

test('filterWeixinMarkdown strips fenced blocks and inline markers', () => {
  const input = [
    '##### Title',
    '',
    'Before **bold** and `code`.',
    '```ts',
    'const hidden = true;',
    '```',
    '> quoted line',
    'After _italic_ and ~~strike~~.',
  ].join('\n');

  const output = filterWeixinMarkdown(input);

  assert.equal(
    output,
    ['Title', '', 'Before bold and code.', 'const hidden = true;', 'quoted line', 'After italic and strike.'].join('\n'),
  );
});

test('filterWeixinMarkdown keeps table cell text but removes table syntax', () => {
  const input = '| col1 | col2 |\n| --- | --- |\n| a | b |\n';
  const output = filterWeixinMarkdown(input);

  assert.equal(output, 'col1 | col2\n--- | ---\na | b\n');
});
