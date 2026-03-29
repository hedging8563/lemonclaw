import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export type ConductorAgentStatus = 'idle' | 'busy' | 'error' | string;
export type ConductorSubtaskStatus = 'pending' | 'running' | 'completed' | 'failed' | string;

export interface ConductorAgent {
  id: string;
  role?: string;
  model?: string;
  status: ConductorAgentStatus;
  skills?: string[];
  task_count?: number;
  success_rate?: number;
  last_active_ms?: number;
  created_at_ms?: number;
}

export interface ConductorArtifact {
  artifact_id?: string;
  id?: string;
  kind?: string;
  label?: string;
  title?: string;
  preview?: string;
  uri?: string;
  source?: string;
}

export interface ConductorPlannerSummary {
  summary?: string | null;
  role_hint?: string | null;
  depends_on_count?: number | null;
}

export interface ConductorGeneratorSummary {
  status?: string | null;
  output_kind?: string | null;
  summary?: string | null;
  preview?: string | null;
}

export interface ConductorEvaluationSummary {
  status?: string | null;
  score?: number | null;
  confidence?: number | null;
  summary?: string | null;
  warnings?: string[];
}

export interface ConductorObservabilitySummary {
  phase?: string | null;
  progress?: number | null;
  trace_id?: string | null;
  execution_mode?: string | null;
  attempt_count?: number | null;
  attempts?: number | null;
  duration_ms?: number | null;
  agent_id?: string | null;
  started_at_ms?: number | null;
  completed_at_ms?: number | null;
  queued_at_ms?: number | null;
  ended_at_ms?: number | null;
  updated_at_ms?: number | null;
  error_count?: number | null;
  last_error?: string | null;
  error?: string | null;
}

export interface ConductorSubtask {
  id: string;
  description: string;
  role_hint?: string | null;
  role_label?: string | null;
  status: ConductorSubtaskStatus;
  state_bucket?: string;
  assigned_agent?: string | null;
  planner?: ConductorPlannerSummary | null;
  generator?: ConductorGeneratorSummary | null;
  evaluation?: ConductorEvaluationSummary | null;
  artifacts?: ConductorArtifact[] | null;
  artifact_count?: number | null;
  observability?: ConductorObservabilitySummary | null;
  depends_on?: string[];
  dependency_descriptions?: string[];
  result_preview?: string | null;
}

export interface ConductorPlan {
  request_id: string;
  phase?: string;
  message: string;
  complexity?: string;
  intent?: {
    summary?: string;
  } | null;
  swarm_template_id?: string | null;
  swarm_template_label?: string | null;
  swarm_goal?: string | null;
  planner?: Record<string, unknown> | null;
  generator?: Record<string, unknown> | null;
  merge?: Record<string, unknown> | null;
  evaluator?: Record<string, unknown> | null;
  artifacts?: { count?: number | null; items?: ConductorArtifact[] } | null;
  observability?: ConductorObservabilitySummary | null;
  team_roles?: ConductorTemplateRole[];
  subtasks?: ConductorSubtask[];
  progress?: number;
}

export interface ConductorTemplateRole {
  id: string;
  label: string;
  skills?: string[];
}

export interface ConductorTemplate {
  id: string;
  label: string;
  keywords?: string[];
  roles?: ConductorTemplateRole[];
}

type AgentsResponse = { agents?: ConductorAgent[] };
type PlansResponse = { plans?: ConductorPlan[] };
type TemplatesResponse = { templates?: ConductorTemplate[] };

export const agents = signal<ConductorAgent[]>([]);
export const plans = signal<ConductorPlan[]>([]);
export const templates = signal<ConductorTemplate[]>([]);

export async function loadConductor() {
  try {
    const [agentsRes, plansRes, templatesRes] = await Promise.all([
      apiFetch('/api/conductor/agents'),
      apiFetch('/api/conductor/plans'),
      apiFetch('/api/conductor/templates'),
    ]);
    const agentsData = (await agentsRes.json()) as AgentsResponse;
    const plansData = (await plansRes.json()) as PlansResponse;
    const templatesData = (await templatesRes.json()) as TemplatesResponse;
    agents.value = agentsData.agents || [];
    plans.value = plansData.plans || [];
    templates.value = templatesData.templates || [];
  } catch (err) {
    console.error("Failed to load conductor data", err);
  }
}
