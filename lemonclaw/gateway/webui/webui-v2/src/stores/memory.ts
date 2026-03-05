import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const memory = signal<any>(null);

export async function loadMemory() {
  try {
    const res = await apiFetch('/api/memory');
    const data = await res.json();
    memory.value = data;
  } catch (err) {
    console.error("Failed to load memory data", err);
  }
}