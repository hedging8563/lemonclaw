import { useEffect, useRef, useState } from 'preact/hooks';
import { agents, plans, templates, loadConductor } from '../../stores/conductor';
import { t } from '../../stores/i18n';

const shellStyle = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, var(--bg-secondary) 100%)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '14px',
  boxShadow: '0 12px 26px rgba(0,0,0,0.14)',
} as const;

const workboardStyle = {
  display: 'grid',
  gap: '12px',
  marginTop: '12px',
} as const;

const laneGridStyle = {
  display: 'grid',
  gap: '10px',
  gridTemplateColumns: 'repeat(auto-fit, minmax(245px, 1fr))',
} as const;

const laneCardStyle = {
  display: 'grid',
  gap: '10px',
  padding: '12px',
  background: 'var(--bg-primary)',
  border: '1px solid var(--border)',
  borderRadius: '10px',
  overflow: 'hidden',
} as const;

const laneSubtaskStyle = {
  display: 'grid',
  gap: '8px',
  padding: '10px',
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
} as const;

const subtaskMetaGridStyle = {
  display: 'grid',
  gap: '8px',
  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
} as const;

const subtaskMetaCardStyle = {
  display: 'grid',
  gap: '6px',
  padding: '8px 10px',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  background: 'var(--bg-primary)',
} as const;

const subtaskMetaLabelStyle = {
  fontSize: '11px',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-muted)',
  fontFamily: 'var(--font-ui)',
} as const;

const subtaskMetaValueStyle = {
  fontSize: '13px',
  color: 'var(--text-primary)',
  lineHeight: 1.45,
  wordBreak: 'break-word',
  whiteSpace: 'pre-wrap',
} as const;

const subtaskMetaNoteStyle = {
  fontSize: '12px',
  color: 'var(--text-secondary)',
  lineHeight: 1.45,
  wordBreak: 'break-word',
  whiteSpace: 'pre-wrap',
} as const;

const subtaskArtifactRowStyle = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: '6px',
  alignItems: 'center',
} as const;

function pillStyle(active = false) {
  return {
    padding: '6px 10px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(10, 186, 181, 0.12)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-ui)',
    fontSize: '13px',
    cursor: 'pointer',
  } as const;
}

function stateChipStyle(state: 'ready' | 'running' | 'blocked' | 'completed' | 'failed') {
  const palette = {
    ready: {
      background: 'rgba(100, 149, 237, 0.12)',
      borderColor: 'rgba(100, 149, 237, 0.28)',
      color: 'cornflowerblue',
    },
    running: {
      background: 'rgba(10, 186, 181, 0.12)',
      borderColor: 'rgba(10, 186, 181, 0.28)',
      color: 'var(--accent)',
    },
    blocked: {
      background: 'rgba(255, 170, 0, 0.12)',
      borderColor: 'rgba(255, 170, 0, 0.28)',
      color: 'var(--warning, #ffb84d)',
    },
    completed: {
      background: 'rgba(76, 175, 80, 0.12)',
      borderColor: 'rgba(76, 175, 80, 0.28)',
      color: 'var(--success)',
    },
    failed: {
      background: 'rgba(255, 68, 68, 0.12)',
      borderColor: 'rgba(255, 68, 68, 0.28)',
      color: 'var(--error)',
    },
  } as const;

  return {
    padding: '4px 8px',
    borderRadius: '999px',
    border: '1px solid',
    background: palette[state].background,
    borderColor: palette[state].borderColor,
    color: palette[state].color,
    fontFamily: 'var(--font-ui)',
    fontSize: '11px',
    letterSpacing: '0.02em',
    textTransform: 'uppercase',
    whiteSpace: 'nowrap',
    cursor: 'default',
  } as const;
}

function truncateText(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function normalizeKey(value: unknown) {
  return String(value ?? '').trim().toLowerCase();
}

function getLaneId(subtask: any) {
  const hinted = String(subtask?.role_hint || '').trim();
  if (hinted) return hinted;
  const assigned = String(subtask?.assigned_agent_id || subtask?.assigned_agent || '').trim();
  if (assigned.startsWith('swarm-')) {
    const parts = assigned.split('-');
    const role = parts[parts.length - 1];
    if (role) return role;
  }
  return assigned || 'unassigned';
}

function getTemplateLaneLabel(template: any, laneId: string) {
  if (laneId === 'unassigned') return t('conductor_lane_unassigned');
  const role = (template?.roles || []).find((item: any) => item.id === laneId);
  return role?.label || laneId;
}

function isDependencyComplete(subtask: any) {
  return normalizeKey(subtask?.status) === 'completed';
}

function getDerivedState(subtask: any, byId: Map<string, any>) {
  const raw = normalizeKey(subtask?.status) || 'pending';
  if (raw === 'completed' || raw === 'done') {
    return { key: 'completed' as const, label: t('conductor_lane_completed'), tone: 'completed' as const };
  }
  if (raw === 'running' || raw === 'executing' || raw === 'in_progress') {
    return { key: 'running' as const, label: t('conductor_lane_running'), tone: 'running' as const };
  }
  if (raw === 'failed' || raw === 'error') {
    return { key: 'blocked' as const, label: t('conductor_lane_failed'), tone: 'failed' as const };
  }

  const dependencyIds = Array.isArray(subtask?.depends_on) ? subtask.depends_on : [];
  const hasOpenDependency = dependencyIds.some((depId: string) => !isDependencyComplete(byId.get(depId)));
  if (hasOpenDependency) {
    return { key: 'blocked' as const, label: t('conductor_lane_blocked'), tone: 'blocked' as const };
  }
  return { key: 'ready' as const, label: t('conductor_lane_ready'), tone: 'ready' as const };
}

function buildLaneIds(template: any, subtasks: any[]) {
  const ordered = new Set<string>();
  for (const role of template?.roles || []) {
    ordered.add(role.id);
  }
  for (const subtask of subtasks) {
    ordered.add(getLaneId(subtask));
  }
  return Array.from(ordered);
}

function summarizeStates(subtasks: any[], byId: Map<string, any>) {
  return subtasks.reduce(
    (acc, subtask) => {
      const derived = getDerivedState(subtask, byId);
      acc[derived.key] += 1;
      return acc;
    },
    { ready: 0, running: 0, blocked: 0, completed: 0 },
  );
}

function formatSummaryChip(label: string, count: number, tone: 'ready' | 'running' | 'blocked' | 'completed') {
  return (
    <span style={{ ...stateChipStyle(tone), cursor: 'default' }}>
      {label}: {count}
    </span>
  );
}

function formatMaybeCount(value: number | null | undefined) {
  return typeof value === 'number' ? String(value) : '—';
}

function formatMaybeText(value: unknown) {
  const text = String(value ?? '').trim();
  return text || '—';
}

function formatDurationMs(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value) || value < 0) return '—';
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
  const minutes = Math.floor(value / 60000);
  const seconds = Math.round((value % 60000) / 1000);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function formatShortId(value: string | null | undefined, maxLength = 12) {
  const text = String(value ?? '').trim();
  if (!text) return '—';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}

function getEvaluationTone(status: string | null | undefined) {
  const normalized = normalizeKey(status);
  if (['passed', 'pass', 'completed', 'success', 'ok', 'ready'].includes(normalized)) return 'completed' as const;
  if (['failed', 'fail', 'error'].includes(normalized)) return 'failed' as const;
  if (['warning', 'review', 'needs_review'].includes(normalized)) return 'blocked' as const;
  if (['running', 'processing', 'pending', 'queued', 'checking'].includes(normalized)) return 'running' as const;
  return 'ready' as const;
}

export function ConductorPanel() {
  const timerRef = useRef<any>(null);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    void loadConductor();

    const startPolling = () => {
      if (timerRef.current) clearInterval(timerRef.current);
      const hasBusy = agents.peek().some((agent) => agent.status === 'busy');
      timerRef.current = setInterval(() => {
        if (document.visibilityState === 'visible') {
          void loadConductor().then(() => {
            const nowBusy = agents.peek().some((agent) => agent.status === 'busy');
            if (nowBusy !== hasBusy) startPolling();
          });
        }
      }, hasBusy ? 3000 : 15000);
    };

    startPolling();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const conductorBusy = agents.value.some((agent) => agent.status === 'busy');
  const busyAgents = agents.value.filter((agent) => agent.status === 'busy').length;
  const errorAgents = agents.value.filter((agent) => agent.status === 'error').length;
  const activePlan = plans.value[0] ?? null;
  const activeTemplate = activePlan ? templates.value.find((template) => template.id === activePlan.swarm_template_id) ?? null : null;
  const activeSubtasks = Array.isArray(activePlan?.subtasks) ? activePlan.subtasks : [];
  const activeById = new Map(activeSubtasks.map((subtask: any) => [subtask.id, subtask] as const));
  const activeCounts = summarizeStates(activeSubtasks, activeById);
  const activeIntentSummary = (activePlan as any)?.intent?.summary;
  const summaryMessage = activePlan?.message || t('no_plans');
  const planPlanner = (activePlan as any)?.planner || {};
  const planGenerator = (activePlan as any)?.generator || {};
  const planMerge = (activePlan as any)?.merge || {};
  const planEvaluator = (activePlan as any)?.evaluator || {};
  const planArtifacts = (activePlan as any)?.artifacts || {};
  const planObservability = (activePlan as any)?.observability || {};

  return (
    <div style={shellStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '13px', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>// {t('conductor_title')}</span>
            {conductorBusy ? <span style={{ width: '6px', height: '6px', background: 'var(--accent)', borderRadius: '50%', animation: 'server-blink 1s infinite' }} /> : null}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
            <span style={pillStyle(Boolean(plans.value.length))}>{`plans: ${plans.value.length}`}</span>
            <span style={pillStyle(Boolean(busyAgents))}>{`busy: ${busyAgents}`}</span>
            <span style={pillStyle(Boolean(errorAgents))}>{`errors: ${errorAgents}`}</span>
            <span style={pillStyle()}>{`agents: ${agents.value.length}`}</span>
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{summaryMessage}</div>
        </div>
        <button onClick={() => setExpanded((value) => !value)} style={pillStyle(expanded)}>
          {expanded ? t('memo_collapse') : t('memo_expand')}
        </button>
      </div>

      {expanded ? (
        <div style={{ display: 'grid', gap: '12px' }}>
          {activePlan ? (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '10px', padding: '12px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px', marginBottom: '10px' }}>
                <div style={{ minWidth: 0, flex: 1, display: 'grid', gap: '8px' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    <span style={{ ...pillStyle(Boolean(activeTemplate)), cursor: 'default' }}>{`${t('conductor_active_team')}: ${activePlan.swarm_template_label || activeTemplate?.label || t('conductor_lane_unassigned')}`}</span>
                    <span style={{ ...pillStyle(), cursor: 'default' }}>{`${t('conductor_active_phase')}: ${activePlan.phase || 'UNKNOWN'}`}</span>
                    {activePlan.complexity ? <span style={{ ...pillStyle(), cursor: 'default' }}>{`lvl:${activePlan.complexity}`}</span> : null}
                    <span style={{ ...pillStyle(Boolean(activeSubtasks.length)), cursor: 'default' }}>{`lanes: ${buildLaneIds(activeTemplate, activeSubtasks).length}`}</span>
                  </div>
                  <div style={{ display: 'grid', gap: '4px', color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.5 }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: '6px' }}>
                        {t('conductor_active_goal')}
                      </span>
                      <span style={{ color: 'var(--text-primary)' }}>{activePlan.swarm_goal || activeIntentSummary || summaryMessage}</span>
                    </div>
                    {activePlan.message ? <div>{activePlan.message}</div> : null}
                  </div>
                </div>
                <div style={{ display: 'grid', gap: '6px', justifyItems: 'end' }}>
                  <span style={{ ...pillStyle(activeCounts.blocked > 0), cursor: 'default' }}>{`${t('conductor_lane_blocked')}: ${activeCounts.blocked}`}</span>
                  <span style={{ ...pillStyle(activeCounts.running > 0), cursor: 'default' }}>{`${t('conductor_lane_running')}: ${activeCounts.running}`}</span>
                  <span style={{ ...pillStyle(activeCounts.ready > 0), cursor: 'default' }}>{`${t('conductor_lane_ready')}: ${activeCounts.ready}`}</span>
                  <span style={{ ...pillStyle(activeCounts.completed > 0), cursor: 'default' }}>{`${t('conductor_lane_completed')}: ${activeCounts.completed}`}</span>
                </div>
              </div>

              <div style={workboardStyle}>
                <div style={subtaskMetaGridStyle}>
                  <div style={{ ...subtaskMetaCardStyle, background: 'var(--bg-secondary)' }}>
                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_planner')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ ...stateChipStyle(getEvaluationTone(planPlanner.status)), cursor: 'default' }}>{formatMaybeText(planPlanner.status)}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`subtasks ${formatMaybeCount(planPlanner.subtask_count ?? activeSubtasks.length)}`}</span>
                    </div>
                    <div style={subtaskMetaValueStyle}>{formatMaybeText(planPlanner.summary || activePlan.swarm_goal || activeIntentSummary || summaryMessage)}</div>
                    <div style={subtaskMetaNoteStyle}>{formatMaybeText(planPlanner.reasoning)}</div>
                  </div>
                  <div style={{ ...subtaskMetaCardStyle, background: 'var(--bg-secondary)' }}>
                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_generator')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ ...stateChipStyle(getEvaluationTone(planGenerator.status)), cursor: 'default' }}>{formatMaybeText(planGenerator.status)}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`done ${formatMaybeCount(planGenerator.completed_count)}`}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`running ${formatMaybeCount(planGenerator.running_count)}`}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`failed ${formatMaybeCount(planGenerator.failed_count)}`}</span>
                    </div>
                    <div style={subtaskMetaValueStyle}>{formatMaybeText(planGenerator.summary || `${formatMaybeCount(planGenerator.completed_count)} completed of ${formatMaybeCount(planGenerator.subtask_count ?? activeSubtasks.length)} subtasks`)}</div>
                  </div>
                  <div style={{ ...subtaskMetaCardStyle, background: 'var(--bg-secondary)' }}>
                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_merge')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ ...stateChipStyle(getEvaluationTone(planMerge.status)), cursor: 'default' }}>{formatMaybeText(planMerge.status)}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`${t('conductor_section_artifact_count')}: ${formatMaybeCount(planMerge.artifact_count)}`}</span>
                    </div>
                    <div style={subtaskMetaValueStyle}>{formatMaybeText(planMerge.summary)}</div>
                    <div style={subtaskMetaNoteStyle}>{formatMaybeText(planMerge.result_preview)}</div>
                  </div>
                  <div style={{ ...subtaskMetaCardStyle, background: 'var(--bg-secondary)' }}>
                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_evaluator')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ ...stateChipStyle(getEvaluationTone(planEvaluator.plan_status || planEvaluator.status)), cursor: 'default' }}>{formatMaybeText(planEvaluator.plan_status || planEvaluator.status)}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`accepted ${formatMaybeCount(planEvaluator.accepted_count)}`}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`warning ${formatMaybeCount(planEvaluator.warning_count)}`}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`failed ${formatMaybeCount(planEvaluator.failed_count)}`}</span>
                    </div>
                    <div style={subtaskMetaValueStyle}>{formatMaybeText(planEvaluator.plan_reason || planEvaluator.summary)}</div>
                    {typeof planEvaluator.plan_confidence === 'number' ? (
                      <div style={subtaskMetaNoteStyle}>{`${t('conductor_section_confidence')}: ${planEvaluator.plan_confidence.toFixed(2)}`}</div>
                    ) : null}
                  </div>
                  <div style={{ ...subtaskMetaCardStyle, background: 'var(--bg-secondary)' }}>
                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_observability')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`${t('conductor_section_phase')}: ${formatMaybeText(planObservability.phase || activePlan.phase)}`}</span>
                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`${t('conductor_section_duration')}: ${formatDurationMs(planObservability.duration_ms)}`}</span>
                    </div>
                    <div style={subtaskMetaValueStyle}>{`${t('conductor_section_trace')}: ${formatShortId(planObservability.trace_id, 16)}`}</div>
                    <div style={subtaskMetaNoteStyle}>{`${t('conductor_section_artifacts')}: ${formatMaybeCount(planArtifacts.count)} · progress ${typeof activePlan.progress === 'number' ? `${Math.round(activePlan.progress * 100)}%` : '—'}`}</div>
                  </div>
                </div>

                <div style={{ fontFamily: 'var(--font-ui)', fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  {t('conductor_workboard_title')}
                </div>

                {activeSubtasks.length === 0 ? (
                  <div style={{ padding: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-muted)', fontSize: '13px' }}>
                    {t('conductor_lane_no_subtasks')}
                  </div>
                ) : (
                  <div style={laneGridStyle}>
                    {buildLaneIds(activeTemplate, activeSubtasks).map((laneId) => {
                      const laneSubtasks = activeSubtasks.filter((subtask: any) => getLaneId(subtask) === laneId);
                      const laneById = new Map(activeSubtasks.map((subtask: any) => [subtask.id, subtask] as const));
                      const laneCounts = summarizeStates(laneSubtasks, laneById);
                      const laneLabel = getTemplateLaneLabel(activeTemplate, laneId);

                      return (
                        <div key={laneId} style={laneCardStyle}>
                          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                            <div style={{ minWidth: 0, display: 'grid', gap: '4px' }}>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                <span style={{ ...pillStyle(true), cursor: 'default' }}>{laneLabel}</span>
                                <span style={{ ...pillStyle(), cursor: 'default' }}>{laneId}</span>
                              </div>
                              <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)' }}>
                                {laneSubtasks.length ? `${laneSubtasks.length} subtasks` : t('conductor_lane_no_subtasks')}
                              </div>
                            </div>
                            <div style={{ display: 'grid', gap: '4px', justifyItems: 'end' }}>
                              {formatSummaryChip(t('conductor_lane_blocked'), laneCounts.blocked, 'blocked')}
                              {formatSummaryChip(t('conductor_lane_running'), laneCounts.running, 'running')}
                              {formatSummaryChip(t('conductor_lane_ready'), laneCounts.ready, 'ready')}
                              {formatSummaryChip(t('conductor_lane_completed'), laneCounts.completed, 'completed')}
                            </div>
                          </div>

                          <div style={{ display: 'grid', gap: '8px' }}>
                            {laneSubtasks.length === 0 ? null : laneSubtasks.map((subtask: any) => {
                              const derived = getDerivedState(subtask, laneById);
                              const dependencyIds = Array.isArray(subtask.depends_on) ? subtask.depends_on : [];
                              const planSummary = formatMaybeText(subtask.planner?.summary || activePlan?.intent?.summary || activePlan?.swarm_goal || activePlan?.message);
                              const plannerRole = formatMaybeText(subtask.planner?.role_hint || subtask.role_hint || subtask.assigned_agent_id);
                              const plannerDependsCount = typeof subtask.planner?.depends_on_count === 'number'
                                ? subtask.planner.depends_on_count
                                : dependencyIds.length;
                              const generatorStatus = formatMaybeText(subtask.generator?.status || subtask.status);
                              const generatorKind = formatMaybeText(subtask.generator?.output_kind || (subtask.artifacts?.length ? subtask.artifacts[0]?.kind : null));
                              const generatorSummary = formatMaybeText(subtask.generator?.summary || subtask.generator?.preview || subtask.result_preview || subtask.description);
                              const evaluationStatus = formatMaybeText(subtask.evaluation?.status || subtask.status);
                              const evaluationTone = getEvaluationTone(subtask.evaluation?.status || subtask.status);
                              const evaluationScore = typeof subtask.evaluation?.score === 'number' ? subtask.evaluation.score : null;
                              const evaluationConfidence = typeof subtask.evaluation?.confidence === 'number' ? subtask.evaluation.confidence : null;
                              const evaluationWarnings = Array.isArray(subtask.evaluation?.warnings) ? subtask.evaluation.warnings.filter(Boolean) : [];
                              const evaluationSummary = formatMaybeText(subtask.evaluation?.summary);
                              const artifacts = Array.isArray(subtask.artifacts) ? subtask.artifacts : [];
                              const artifactCount = typeof subtask.artifact_count === 'number' ? subtask.artifact_count : artifacts.length;
                              const observability = subtask.observability || {};
                              const observabilityParts = [
                                formatMaybeText(observability.execution_mode),
                                formatShortId(observability.agent_id || subtask.assigned_agent_id || subtask.assigned_agent),
                              ].filter((item) => item && item !== '—');
                              const observabilityTrace = formatShortId(observability.trace_id, 16);
                              const observabilityAttempts = formatMaybeCount(observability.attempt_count);
                              const observabilityDuration = formatDurationMs(observability.duration_ms ?? null);
                              const observabilityStarted = observability.started_at_ms ? new Date(observability.started_at_ms).toLocaleString() : '—';
                              const observabilityCompleted = observability.completed_at_ms ? new Date(observability.completed_at_ms).toLocaleString() : '—';
                              const dependencyChips = dependencyIds.map((depId: string) => {
                                const dep = laneById.get(depId) || activeById.get(depId);
                                const depLabel = dep?.description ? truncateText(String(dep.description), 42) : depId;
                                const depState = dep ? getDerivedState(dep, activeById) : { tone: 'blocked' as const, label: t('conductor_lane_blocked') };
                                return (
                                  <span
                                    key={depId}
                                    title={dep?.description || depId}
                                    style={{ ...stateChipStyle(depState.tone), cursor: 'default', textTransform: 'none' }}
                                  >
                                    {depLabel}
                                  </span>
                                );
                              });

                              return (
                                <div key={subtask.id} style={laneSubtaskStyle}>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                                    <span style={{ ...stateChipStyle(derived.tone), cursor: 'default' }}>{derived.label}</span>
                                    {subtask.assigned_agent || subtask.assigned_agent_id ? (
                                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`agent: ${subtask.assigned_agent || subtask.assigned_agent_id}`}</span>
                                    ) : null}
                                    {dependencyIds.length ? <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{`${t('conductor_dependency_handoff')}: ${dependencyIds.length}`}</span> : null}
                                  </div>

                                  <div style={{ color: derived.key === 'completed' ? 'var(--text-muted)' : 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
                                    {subtask.description}
                                  </div>

                                  <div style={subtaskMetaGridStyle}>
                                    <div style={subtaskMetaCardStyle}>
                                      <div style={subtaskMetaLabelStyle}>{t('conductor_section_planner')}</div>
                                      <div style={subtaskMetaValueStyle}>{planSummary}</div>
                                      <div style={subtaskMetaNoteStyle}>
                                        {`${t('conductor_section_planner_meta')}: ${plannerRole} · ${plannerDependsCount}`}
                                      </div>
                                    </div>
                                    <div style={subtaskMetaCardStyle}>
                                      <div style={subtaskMetaLabelStyle}>{t('conductor_section_generator')}</div>
                                      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                                        <span style={{ ...stateChipStyle(getEvaluationTone(generatorStatus)), cursor: 'default' }}>{generatorStatus}</span>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{generatorKind}</span>
                                      </div>
                                      <div style={subtaskMetaValueStyle}>{generatorSummary}</div>
                                    </div>
                                    <div style={subtaskMetaCardStyle}>
                                      <div style={subtaskMetaLabelStyle}>{t('conductor_section_evaluator')}</div>
                                      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                                        <span style={{ ...stateChipStyle(evaluationTone), cursor: 'default' }}>{evaluationStatus}</span>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {evaluationScore != null
                                            ? `${t('conductor_section_score')}: ${evaluationScore.toFixed(2)}`
                                            : t('conductor_section_score_missing')}
                                        </span>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {evaluationConfidence != null
                                            ? `${t('conductor_section_confidence')}: ${evaluationConfidence.toFixed(2)}`
                                            : t('conductor_section_confidence_missing')}
                                        </span>
                                      </div>
                                      <div style={subtaskMetaValueStyle}>{evaluationSummary}</div>
                                      {evaluationWarnings.length ? (
                                        <div style={subtaskMetaNoteStyle}>
                                          {`${t('conductor_section_warnings')}: ${evaluationWarnings.length}`}
                                        </div>
                                      ) : null}
                                    </div>
                                    <div style={subtaskMetaCardStyle}>
                                      <div style={subtaskMetaLabelStyle}>{t('conductor_section_observability')}</div>
                                      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {`${t('conductor_section_trace')}: ${observabilityTrace}`}
                                        </span>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {`${t('conductor_section_attempts')}: ${observabilityAttempts}`}
                                        </span>
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {`${t('conductor_section_duration')}: ${observabilityDuration}`}
                                        </span>
                                      </div>
                                      <div style={subtaskMetaValueStyle}>
                                        {observabilityParts.length ? observabilityParts.join(' · ') : t('conductor_section_no_observability')}
                                      </div>
                                      <div style={subtaskMetaNoteStyle}>
                                        {`${t('conductor_section_started_completed')}: ${observabilityStarted} → ${observabilityCompleted}`}
                                      </div>
                                      {observability.error ? (
                                        <div style={{ ...subtaskMetaNoteStyle, color: 'var(--error)' }}>
                                          {formatMaybeText(observability.error)}
                                        </div>
                                      ) : null}
                                    </div>
                                  </div>

                                  <div style={subtaskMetaCardStyle}>
                                    <div style={subtaskMetaLabelStyle}>{t('conductor_section_artifacts')}</div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
                                      <span style={{ ...pillStyle(Boolean(artifactCount)), cursor: 'default', fontSize: '11px' }}>
                                        {`${t('conductor_section_artifact_count')}: ${artifactCount}`}
                                      </span>
                                      {!artifacts.length && artifactCount === 0 ? (
                                        <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>
                                          {t('conductor_section_no_artifacts')}
                                        </span>
                                      ) : null}
                                    </div>
                                    {artifacts.length ? (
                                      <div style={{ display: 'grid', gap: '6px' }}>
                                        {artifacts.slice(0, 3).map((artifact: any) => (
                                          <div key={artifact.artifact_id || artifact.title || artifact.uri || JSON.stringify(artifact)} style={{ display: 'grid', gap: '4px', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-secondary)' }}>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                                              <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{formatMaybeText(artifact.kind)}</span>
                                              <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{formatMaybeText(artifact.title || artifact.artifact_id)}</span>
                                            </div>
                                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
                                              {formatMaybeText(artifact.preview)}
                                            </div>
                                            {artifact.uri ? (
                                              <div style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                                                {artifact.uri}
                                              </div>
                                            ) : null}
                                          </div>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>

                                  {dependencyChips.length ? (
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                                      <span style={{ ...pillStyle(), cursor: 'default', fontSize: '11px' }}>{t('conductor_dependency_handoff')}</span>
                                      {dependencyChips}
                                    </div>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
              <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>{t('no_plans')}</div>
            </div>
          )}

          <details open={agents.value.length <= 6} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', textTransform: 'uppercase', letterSpacing: '1px' }}>
              agent pool · {agents.value.length}
            </summary>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px', maxHeight: '180px', overflowY: 'auto', paddingRight: '4px' }}>
              {agents.value.map((agent) => {
                const isBusy = agent.status === 'busy';
                const isError = agent.status === 'error';
                return (
                  <div
                    key={agent.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      background: isError ? 'rgba(255, 68, 68, 0.1)' : isBusy ? 'rgba(10, 186, 181, 0.1)' : 'var(--bg-secondary)',
                      border: '1px solid',
                      borderColor: isError ? 'rgba(255, 68, 68, 0.3)' : isBusy ? 'rgba(10, 186, 181, 0.3)' : 'var(--border)',
                      padding: '4px 10px',
                      borderRadius: '20px',
                      fontSize: '13px',
                      fontFamily: 'var(--font-ui)',
                    }}
                  >
                    <span style={{ color: isError ? 'var(--error)' : isBusy ? 'var(--teal)' : 'var(--text-muted)', fontSize: '8px' }}>
                      {isError ? '✖' : isBusy ? '●' : '○'}
                    </span>
                    <span style={{ color: isError ? 'var(--error)' : isBusy ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{agent.id}</span>
                  </div>
                );
              })}
            </div>
          </details>

          <details style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', textTransform: 'uppercase', letterSpacing: '1px' }}>
              templates · {templates.value.length}
            </summary>
            <div style={{ display: 'grid', gap: '8px', marginTop: '10px' }}>
              {templates.value.map((template) => (
                <div key={template.id} style={{ border: '1px solid var(--border)', borderRadius: '8px', padding: '10px', background: 'var(--bg-secondary)' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                    <span style={{ ...pillStyle(activePlan?.swarm_template_id === template.id), cursor: 'default' }}>{template.label}</span>
                    <span style={{ ...pillStyle(), cursor: 'default' }}>{template.id}</span>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {(template.roles || []).map((role: any) => (
                      <span key={`${template.id}:${role.id}`} style={{ ...pillStyle(), cursor: 'default', fontSize: '12px' }}>
                        {role.label}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </div>
      ) : null}
    </div>
  );
}
