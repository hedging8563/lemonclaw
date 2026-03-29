import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

let buildTaskOperatorStory: typeof import('./taskOperatorStory').buildTaskOperatorStory;
let lang: typeof import('../stores/i18n').lang;

vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => 'en'),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
});

beforeAll(async () => {
  ({ buildTaskOperatorStory } = await import('./taskOperatorStory'));
  ({ lang } = await import('../stores/i18n'));
});

afterEach(() => {
  lang.value = 'en';
});

describe('buildTaskOperatorStory', () => {
  it('reads a dispatch failure as operator guidance in English', () => {
    lang.value = 'en';

    const story = buildTaskOperatorStory(
      {
        task_id: 'task-1',
        session_key: 'session-7',
        channel: 'whatsapp',
        status: 'running',
        current_stage: 'resume_dispatch_failed',
        display_state: {
          key: 'resume_dispatch_failed',
          label: 'Continue failed to start',
          tone: 'warning',
        },
        resume_context: {
          channel: 'whatsapp',
          chat_id: 'chat-42',
          session_key: 'session-7',
        },
      } as any,
      {
        summary: {
          display_state: {
            key: 'resume_dispatch_failed',
            label: 'Continue failed to start',
            tone: 'warning',
          },
          last_successful_step: 'collect request',
          resume_from_step: 'send reply',
        },
        candidate: {
          recommended_action: 'retry_resume_dispatch',
          safe_to_execute: true,
        },
      } as any,
    );

    expect(story.statusLabel).toBe('Continue failed to start');
    expect(story.happened).toBe('The task was ready to continue, but the handoff did not start. Retry here.');
    expect(story.nextStep).toBe('Retry start');
    expect(story.where).toBe('channel whatsapp · chat chat-42 · session session-7');
    expect(story.whereHint).toBe('Retry here:');
    expect(story.checkpoint).toBe('Last confirmed step: collect request · Resume from: send reply');
  });

  it('reads replayable failures as plain operator guidance in Chinese', () => {
    lang.value = 'zh';

    const story = buildTaskOperatorStory(
      {
        task_id: 'task-2',
        session_key: 'session-8',
        channel: 'feishu',
        status: 'running',
        current_stage: 'running',
        display_state: {
          key: 'running',
          label: '运行中',
          tone: 'accent',
        },
        resume_context: {
          channel: 'feishu',
          chat_id: 'chat-88',
          session_key: 'session-8',
        },
      } as any,
      {
        summary: {
          display_state: {
            key: 'running',
            label: '运行中',
            tone: 'accent',
          },
        },
        candidate: {
          recommended_action: 'replay_failed_steps',
          replayable_failed_count: 2,
        },
      } as any,
    );

    expect(story.statusLabel).toBe('处理中');
    expect(story.happened).toBe('有 2 个失败步骤可以重试。');
    expect(story.nextStep).toBe('重试失败步骤');
    expect(story.where).toBe('channel feishu · chat chat-88 · session session-8');
    expect(story.whereHint).toBe('去这里检查：');
  });
});
