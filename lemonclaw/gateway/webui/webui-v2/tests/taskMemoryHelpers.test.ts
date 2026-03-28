import { describe, expect, it } from 'vitest';
import { buildStructuredMemoryWorkSurface, type TaskDetail, type TaskRecord } from '../src/stores/tasks';

function task(task_id: string, patch: Partial<TaskRecord> = {}): TaskRecord {
  return {
    task_id,
    session_key: 'webui:test',
    agent_id: 'default',
    mode: 'chat',
    channel: 'webui',
    goal: task_id,
    status: 'running',
    current_stage: 'execute',
    updated_at_ms: 0,
    ...patch,
  };
}

describe('buildStructuredMemoryWorkSurface', () => {
  it('prefers the most recent task with structured retrieval', () => {
    const older = task('task-old', {
      goal: 'older task',
      updated_at_ms: 100,
      retrieval: {
        structured: {
          session_summary: 'older summary',
          fact_slots: [{ name: 'lang', type: 'fact', summary: 'python' }],
          retrieval_objects: [{ kind: 'entity_card', title: 'lang', source: 'memory.entities' }],
        },
      },
    });
    const newer = task('task-new', {
      goal: 'newer task',
      updated_at_ms: 200,
      retrieval: {
        strategy: 'hybrid',
        latency_ms: 15,
        fallback_count: 1,
        fallbacks: ['knowledge_search_error:RuntimeError'],
        hit_sources: ['hybrid', 'knowledge'],
        structured: {
          session_summary: 'latest summary',
          fact_slots: [{ name: 'stack', type: 'fact', summary: 'python 3.13' }],
          retrieval_objects: [{ kind: 'knowledge_hit', title: 'Deploy Notes', source: 'manual://deploy' }],
        },
      },
    });

    const result = buildStructuredMemoryWorkSurface([older, newer], {});

    expect(result?.sourceTaskId).toBe('task-new');
    expect(result?.sourceGoal).toBe('newer task');
    expect(result?.strategy).toBe('hybrid');
    expect(result?.latencyMs).toBe(15);
    expect(result?.sessionSummary).toBe('latest summary');
    expect(result?.factSlots[0]?.name).toBe('stack');
    expect(result?.retrievalObjects[0]?.kind).toBe('knowledge_hit');
    expect(result?.fallbackCount).toBe(1);
    expect(result?.fallbacks).toEqual(['knowledge_search_error:RuntimeError']);
    expect(result?.hitSources).toEqual(['hybrid', 'knowledge']);
  });

  it('uses detail summary retrieval when the task list record has no retrieval', () => {
    const pending = task('task-detail', {
      goal: 'detail-backed task',
      updated_at_ms: 300,
    });
    const details: Record<string, TaskDetail> = {
      'task-detail': {
        task: pending,
        summary: {
          retrieval: {
            structured: {
              session_summary: 'detail summary',
              fact_slots: [],
              retrieval_objects: [{ kind: 'entity_card', title: 'ops', source: 'memory.entities' }],
            },
            hit_sources: ['memory'],
          },
        },
      },
    };

    const result = buildStructuredMemoryWorkSurface([pending], details);

    expect(result?.sourceTaskId).toBe('task-detail');
    expect(result?.sessionSummary).toBe('detail summary');
    expect(result?.retrievalObjects[0]?.title).toBe('ops');
    expect(result?.hitSources).toEqual(['memory']);
  });

  it('returns null when no task carries structured retrieval or diagnostics', () => {
    const idle = task('task-empty', { updated_at_ms: 400 });
    expect(buildStructuredMemoryWorkSurface([idle], {})).toBeNull();
  });
});
