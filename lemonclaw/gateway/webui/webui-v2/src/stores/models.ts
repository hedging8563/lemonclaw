import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const models = signal<any[]>([]);
export const currentModel = signal<string>('');

export async function loadModels() {
  try {
    const res = await apiFetch('/api/models');
    const data = await res.json();
    models.value = data.models || [];
    currentModel.value = data.current || '';
  } catch (err) {
    console.error("Failed to load models", err);
  }
}