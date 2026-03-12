import { describe, expect, it } from 'vitest';
import { modelMetaLabel, modelOptionLabel, profileLabel } from '../src/components/layout/modelPresentation';

const dict: Record<string, string> = {
  model_profile_default: 'Default',
  model_profile_standard_chat: 'Daily Chat',
  model_profile_flagship_reasoning: 'Flagship Reasoning',
  model_source_runtime: 'Managed by runtime',
  model_source_builtin: 'Built-in',
};

const t = (key: string) => dict[key] || key;

describe('modelPresentation', () => {
  it('maps internal profiles to human labels', () => {
    expect(profileLabel('standard_chat', t)).toBe('Daily Chat');
    expect(profileLabel('flagship_reasoning', t)).toBe('Flagship Reasoning');
    expect(profileLabel(null, t)).toBe('Default');
  });

  it('builds user-friendly model option labels', () => {
    expect(modelOptionLabel({ id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', source: 'runtime-policy', profile: 'standard_chat' }, t))
      .toBe('Claude Sonnet 4.6 · Daily Chat');
    expect(modelOptionLabel({ id: 'gpt-5.4', label: 'GPT-5.4', source: 'builtin' }, t))
      .toBe('GPT-5.4');
  });

  it('builds user-friendly meta labels', () => {
    expect(modelMetaLabel({ id: 'claude-sonnet-4-6', source: 'runtime-policy', profile: 'standard_chat' }, t))
      .toBe('Managed by runtime · Daily Chat');
    expect(modelMetaLabel({ id: 'gpt-5.4', source: 'builtin' }, t))
      .toBe('Built-in');
  });
});
