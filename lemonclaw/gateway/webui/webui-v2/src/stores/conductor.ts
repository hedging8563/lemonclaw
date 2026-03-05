import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const agents = signal<any[]>([]);
export const plans = signal<any[]>([]);

export async function loadConductor() {
  try {
    const [agentsRes, plansRes] = await Promise.all([
      apiFetch('/api/conductor/agents'),
      apiFetch('/api/conductor/plans')
    ]);
    const agentsData = await agentsRes.json();
    const plansData = await plansRes.json();
    agents.value = agentsData.agents || [];
    plans.value = plansData.plans || [];
  } catch (err) {
    console.error("Failed to load conductor data", err);
  }
}