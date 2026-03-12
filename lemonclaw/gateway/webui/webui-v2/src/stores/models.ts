import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

type ModelOption = {
  id: string;
  label?: string;
  tier?: string;
  description?: string;
  source?: string;
  profile?: string | null;
  runtimePolicyActive?: boolean;
};

export const models = signal<ModelOption[]>([]);
export const currentModel = signal<string>('');
export const globalDefaultModel = signal<string>('');
export const currentModelRuntimeMeta = signal<ModelOption | null>(null);
export const runtimePolicyActive = signal<boolean>(false);

export async function loadModels() {
  try {
    const res = await apiFetch('/api/models');
    const data = await res.json();

    const fetchedModels: ModelOption[] = data.models || [];
    if (!data.runtimePolicyActive) {
      fetchedModels.sort((a, b) => {
        const aName = a.id.toLowerCase();
        const bName = b.id.toLowerCase();
        const isASonnet46 = aName.includes('claude-sonnet-4-6') || aName.includes('claude-sonnet-4.6');
        const isBSonnet46 = bName.includes('claude-sonnet-4-6') || bName.includes('claude-sonnet-4.6');
        const isASonnet45 = aName.includes('claude-sonnet-4-5') || aName.includes('claude-sonnet-4.5');
        const isBSonnet45 = bName.includes('claude-sonnet-4-5') || bName.includes('claude-sonnet-4.5');

        if (isASonnet46 && !isBSonnet46) return -1;
        if (!isASonnet46 && isBSonnet46) return 1;
        if (isASonnet45 && !isBSonnet45) return -1;
        if (!isASonnet45 && isBSonnet45) return 1;
        return 0;
      });
    }

    models.value = fetchedModels;
    globalDefaultModel.value = data.current || '';
    currentModelRuntimeMeta.value = data.currentMeta ? { id: data.current || '', ...data.currentMeta } : null;
    runtimePolicyActive.value = Boolean(data.runtimePolicyActive);
    if (!currentModel.value) currentModel.value = data.current || '';
  } catch (err) {
    console.error('Failed to load models', err);
  }
}

export function getCurrentModelMeta() {
  const listed = models.value.find((model) => model.id === currentModel.value);
  if (listed) return listed;
  if (currentModelRuntimeMeta.value?.id === currentModel.value) return currentModelRuntimeMeta.value;
  if (runtimePolicyActive.value && currentModel.value === globalDefaultModel.value && currentModel.value) {
    return {
      id: currentModel.value,
      source: 'runtime-policy',
      profile: null,
      runtimePolicyActive: true,
    };
  }
  return null;
}
