import { t } from '../stores/i18n';
import type { TaskDetail, TaskDisplayState, TaskRecord } from '../stores/tasks';

function humanizeCode(value?: string | null) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  return raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function formatDisplayState(state?: TaskDisplayState | null): string {
  if (!state) return 'Unknown';
  const translated = t(`task_state_${state.key}` as any);
  return translated === `task_state_${state.key}` ? state.label : translated;
}

function formatDisplayDetail(state?: TaskDisplayState | null): string {
  if (!state) return '—';
  const translated = t(`task_state_detail_${state.key}` as any);
  return translated === `task_state_detail_${state.key}` ? (state.detail || '—') : translated;
}

function suggestedActionLabel(candidate: Record<string, any> | null | undefined): string {
  const key = String(candidate?.recommended_action || '');
  if (!key) return t('task_action_run_safe_resume');
  const translated = t(`task_action_${key}` as any);
  return translated === `task_action_${key}` ? t('task_action_run_safe_resume') : translated;
}

function formatCandidateReason(candidate: Record<string, any> | null | undefined): string {
  if (!candidate) return '—';
  const action = String(candidate.recommended_action || '');
  const failedOutboxCount = Number(candidate.failed_outbox_count || 0);
  const replayableFailedCount = Number(candidate.replayable_failed_count || 0);
  const nonReplayableFailedCount = Number(candidate.non_replayable_failed_count || 0);
  switch (action) {
    case 'retry_outbox':
      return t('task_candidate_reason_retry_outbox').replace('{count}', String(failedOutboxCount));
    case 'replay_failed_steps':
      return t('task_candidate_reason_replay_failed_steps').replace('{count}', String(replayableFailedCount));
    case 'recheck':
      return t('task_candidate_reason_recheck');
    case 'wait_outbox':
      return t('task_candidate_reason_wait_outbox');
    case 'manual_resume':
      if (nonReplayableFailedCount > 0) {
        return t('task_candidate_reason_manual_resume_non_replayable').replace('{count}', String(nonReplayableFailedCount));
      }
      if (String(candidate.reason || '') === 'manual intervention required') {
        return t('task_candidate_reason_manual_intervention');
      }
      return String(candidate.reason || '—');
    case 'noop':
      return t('task_candidate_reason_noop');
    default:
      return String(candidate.reason || '—');
  }
}

function formatRecoveryAction(action?: string | null): string {
  const key = String(action || '').toLowerCase();
  const translated = t(`task_recovery_action_${key}` as any);
  return translated === `task_recovery_action_${key}` ? (action || '—') : translated;
}

function formatResumeRoute(task: TaskRecord): string {
  const ctx = task.resume_context || {};
  const channel = ctx.channel || task.channel || '—';
  const chatId = ctx.chat_id || '—';
  const sessionKey = ctx.session_key || task.session_key || '—';
  return `${channel}:${chatId} · ${sessionKey}`;
}

function workflowInstruction(task: TaskRecord): string {
  const stateKey = task.display_state?.key || '';
  if (stateKey === 'resume_dispatch_failed') {
    return t('task_workflow_next_retry_dispatch');
  }
  if (stateKey === 'resume_manual_only') {
    return t('task_workflow_next_manual_queue');
  }
  if (stateKey === 'resume_requested') {
    return t('task_workflow_next_follow_queue');
  }
  return t('task_workflow_next_review_outbox');
}

function formatCheckpoint(task: TaskRecord, detail?: TaskDetail | null): string {
  const lastSuccessfulStep = detail?.summary?.last_successful_step;
  const resumeFromStep = detail?.summary?.resume_from_step;
  if (lastSuccessfulStep && resumeFromStep) {
    return `${t('task_last_successful_step')}: ${lastSuccessfulStep} · ${t('task_resume_from_step')}: ${resumeFromStep}`;
  }
  if (lastSuccessfulStep) {
    return `${t('task_last_successful_step')}: ${lastSuccessfulStep}`;
  }
  if (resumeFromStep) {
    return `${t('task_resume_from_step')}: ${resumeFromStep}`;
  }
  const recoveryHistory = detail?.summary?.recovery_history || [];
  const lastRecovery = recoveryHistory[recoveryHistory.length - 1];
  if (lastRecovery?.action) {
    const reason = String(lastRecovery.reason || '').trim();
    return reason ? `${formatRecoveryAction(lastRecovery.action)} · ${reason}` : formatRecoveryAction(lastRecovery.action);
  }
  const correction = task.metadata?.runtime_correction;
  if (correction?.message_preview) {
    return correction.message_preview;
  }
  return t('task_operator_story_checkpoint_empty');
}

export function buildTaskOperatorStory(task: TaskRecord, detail?: TaskDetail | null) {
  const state = detail?.summary?.display_state || task.display_state;
  const candidate = detail?.candidate;
  const candidateAction = String(candidate?.recommended_action || '');
  const showSuggestedAction = Boolean(
    candidate &&
    candidateAction &&
    candidateAction !== 'noop' &&
    !['completed', 'abandoned'].includes(task.status || ''),
  );

  return {
    statusLabel: formatDisplayState(state),
    happened: showSuggestedAction ? formatCandidateReason(candidate) : formatDisplayDetail(state),
    nextStep: showSuggestedAction ? suggestedActionLabel(candidate) : formatDisplayState(state),
    nextStepReason: showSuggestedAction ? formatCandidateReason(candidate) : formatDisplayDetail(state),
    where: formatResumeRoute(task),
    whereHint: workflowInstruction(task),
    checkpoint: formatCheckpoint(task, detail),
    rawStateKey: humanizeCode(state?.key || task.status || task.current_stage),
  };
}
