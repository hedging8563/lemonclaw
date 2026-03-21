import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const agents = signal<any[]>([]);
export const plans = signal<any[]>([]);
export const templates = signal<any[]>([]);

export async function loadConductor() {
  try {
    const [agentsRes, plansRes, templatesRes] = await Promise.all([
      apiFetch('/api/conductor/agents'),
      apiFetch('/api/conductor/plans'),
      apiFetch('/api/conductor/templates'),
    ]);
    const agentsData = await agentsRes.json();
    const plansData = await plansRes.json();
    const templatesData = await templatesRes.json();
    agents.value = agentsData.agents || [];
    plans.value = plansData.plans || [];
    templates.value = templatesData.templates || [];
  } catch (err) {
    console.error("Failed to load conductor data", err);
  }
}
