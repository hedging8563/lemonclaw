import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const models = signal<any[]>([]);
export const currentModel = signal<string>('');
export const globalDefaultModel = signal<string>('');

export async function loadModels() {
  try {
    const res = await apiFetch('/api/models');
    const data = await res.json();
    
    // Sort models to put claude-sonnet-4.6 and 4.5 at the top
    let fetchedModels = data.models || [];
    fetchedModels.sort((a: any, b: any) => {
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
    
    models.value = fetchedModels;
    globalDefaultModel.value = data.current || '';
    if (!currentModel.value) currentModel.value = data.current || '';
  } catch (err) {
    console.error("Failed to load models", err);
  }
}