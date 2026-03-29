import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  activeOperatorTaskId,
  buildStructuredMemoryWorkSurface,
  openTaskSurfaceNavigation,
  taskDetails,
  taskSurfaceNavigation,
  type TaskDetail,
  type TaskRecord,
} from '../src/stores/tasks';
import { apiFetch } from '../src/api/client';

vi.mock('../src/api/client', () => ({
  apiFetch: vi.fn(),
}));

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

function jsonResponse(payload: any, ok = true) {
  return {
    ok,
    json: async () => payload,
  };
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  activeOperatorTaskId.value = null;
  taskSurfaceNavigation.value = null;
  taskDetails.value = {};
});

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
    expect(result?.cardHits).toEqual([]);
    expect(result?.ruleHits).toEqual([]);
    expect(result?.knowledgeHits).toEqual([]);
    expect(result?.fallbackCount).toBe(1);
    expect(result?.fallbacks).toEqual(['knowledge_search_error:RuntimeError']);
    expect(result?.hitSources).toEqual(['hybrid', 'knowledge']);
    expect(result?.pipeline.search.active).toBe(true);
    expect(result?.pipeline.search.totalHits).toBe(0);
    expect(result?.pipeline.summarize.factSlotCount).toBe(1);
    expect(result?.pipeline.failsoft.fallbackCount).toBe(1);
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
    expect(result?.pipeline.search.hitSources).toEqual(['memory']);
    expect(result?.pipeline.summarize.hasSessionSummary).toBe(true);
  });

  it('builds a search -> fetch -> summarize -> fail-soft pipeline view', () => {
    const rich = task('task-pipeline', {
      goal: 'pipeline task',
      updated_at_ms: 500,
      retrieval: {
        strategy: 'hybrid',
        latency_ms: 18,
        card_count: 2,
        rule_count: 1,
        knowledge_count: 1,
        card_hits: [{ name: 'stack', type: 'tech', source: 'memory.entities', preview: 'python 3.13' }],
        rule_hits: [{ trigger: 'deploy', lesson: 'check rollback', action: 'verify image', source: 'memory.rules' }],
        knowledge_hits: [{ title: 'Deploy Notes', source: 'manual://deploy', result_type: 'fact', page_label: 'p.1' }],
        hit_sources: ['hybrid', 'knowledge'],
        fallback_count: 2,
        fallbacks: ['provider_unbound', 'knowledge_search_error:RuntimeError'],
        structured: {
          session_summary: 'pipeline summary',
          fact_slots: [{ name: 'stack', type: 'fact', summary: 'python 3.13' }],
          retrieval_objects: [{ kind: 'knowledge_hit', title: 'Deploy Notes', source: 'manual://deploy' }],
        },
      },
    });

    const result = buildStructuredMemoryWorkSurface([rich], {});

    expect(result?.pipeline.search.totalHits).toBe(4);
    expect(result?.pipeline.fetch.totalFetched).toBe(3);
    expect(result?.pipeline.fetch.cardHitCount).toBe(1);
    expect(result?.pipeline.fetch.ruleHitCount).toBe(1);
    expect(result?.pipeline.fetch.knowledgeHitCount).toBe(1);
    expect(result?.pipeline.summarize.factSlotCount).toBe(1);
    expect(result?.pipeline.summarize.retrievalObjectCount).toBe(1);
    expect(result?.pipeline.failsoft.active).toBe(true);
    expect(result?.pipeline.failsoft.fallbacks).toEqual(['provider_unbound', 'knowledge_search_error:RuntimeError']);
  });

  it('returns null when no task carries structured retrieval or diagnostics', () => {
    const idle = task('task-empty', { updated_at_ms: 400 });
    expect(buildStructuredMemoryWorkSurface([idle], {})).toBeNull();
  });
});

describe('task surface navigation', () => {
  it('opens the retrieval surface, selects the task and loads task detail', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/tasks/task-123') {
        return jsonResponse({
          task: task('task-123', {
            goal: 'surface task',
            updated_at_ms: 900,
            retrieval: {
              structured: {
                session_summary: 'surface summary',
                fact_slots: [{ name: 'mode', type: 'fact', summary: 'retrieval' }],
                retrieval_objects: [{ kind: 'knowledge_hit', title: 'Deploy Notes', source: 'manual://deploy' }],
              },
              hit_sources: ['memory'],
            },
          }),
          summary: {
            retrieval: {
              structured: {
                session_summary: 'surface summary',
                fact_slots: [{ name: 'mode', type: 'fact', summary: 'retrieval' }],
                retrieval_objects: [{ kind: 'knowledge_hit', title: 'Deploy Notes', source: 'manual://deploy' }],
              },
              hit_sources: ['memory'],
            },
          },
          steps: [],
        });
      }
      if (path === '/api/tasks/task-123/resume-candidate') {
        return jsonResponse({ candidate: { safe_to_execute: false, recommended_action: 'recheck' } });
      }
      if (path === '/api/outbox?task_id=task-123&limit=50') {
        return jsonResponse({ events: [] });
      }
      throw new Error(`Unexpected API call: ${String(path)}`);
    });

    const detail = await openTaskSurfaceNavigation('task-123');

    expect(activeOperatorTaskId.value).toBe('task-123');
    expect(taskSurfaceNavigation.value).toEqual({ taskId: 'task-123', section: 'retrieval' });
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/api/tasks/task-123');
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/api/tasks/task-123/resume-candidate', { silent404: true });
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/api/outbox?task_id=task-123&limit=50', { silent404: true });
    expect(detail?.task.task_id).toBe('task-123');
    expect(taskDetails.value['task-123']?.summary?.retrieval?.hit_sources).toEqual(['memory']);
  });
});
