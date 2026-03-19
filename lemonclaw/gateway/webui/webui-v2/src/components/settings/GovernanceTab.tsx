import { t } from '../../stores/i18n';

type GovernanceOverview = {
  enabled?: boolean;
  default_autonomy_cap?: string;
  token_ttl_seconds?: number;
  identity_defaults?: { interactive?: string; automation?: string };
  budgets?: { platform_daily_usd?: number | null; tenant_daily_usd?: number | null; default_task_usd?: number | null };
  capabilities?: {
    total?: number;
    enabled_count?: number;
    disabled_count?: number;
    by_risk?: Record<string, number>;
    by_category?: Record<string, number>;
    disabled_capabilities?: string[];
    unbound_secret_count?: number;
    unbound_sandbox_count?: number;
    unbound_secret_capabilities?: string[];
    unbound_sandbox_capabilities?: string[];
  };
  secret_profiles?: { count?: number; configured_count?: number };
  sandbox_profiles?: { count?: number };
};

type KillSwitchView = {
  epoch?: number;
  global?: boolean;
  counts?: { categories?: number; capabilities?: number; agents?: number; tenants?: number };
  categories?: Record<string, boolean>;
  capabilities?: Record<string, boolean>;
};

type GovernanceProfile = {
  name: string;
  kind?: string;
  description?: string;
  field_count?: number;
  configured?: boolean;
  fields?: string[];
  bound_capabilities?: string[];
  allowed_domains?: string[];
  allowed_paths?: string[];
  blocked_commands?: string[];
  max_timeout_seconds?: number | null;
  allow_headed_browser?: boolean | null;
  require_content_boundaries?: boolean | null;
};

type GovernanceAuditRecord = {
  task_id?: string;
  capability_id?: string;
  tool_name?: string;
  result_status?: string;
  actor_identity?: string;
  started_at?: number;
  warnings?: string[];
  secret_profile?: string;
  sandbox_profile?: string;
  approval_policy?: string;
};

type GovernancePayload = {
  overview?: GovernanceOverview;
  secret_profiles?: GovernanceProfile[];
  sandbox_profiles?: GovernanceProfile[];
  kill_switch?: KillSwitchView;
  recent_audit?: GovernanceAuditRecord[];
};

const cardStyle = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '16px',
} as const;

const statValueStyle = {
  fontFamily: 'var(--font-ui)',
  fontSize: '24px',
  color: 'var(--accent)',
  fontWeight: 'bold',
} as const;

const pill = (tone: 'teal' | 'amber' | 'red' | 'slate') => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: '6px',
  borderRadius: '999px',
  padding: '3px 10px',
  fontFamily: 'var(--font-ui)',
  fontSize: '15px',
  border: '1px solid',
  borderColor: tone === 'teal'
    ? 'rgba(45, 212, 191, 0.28)'
    : tone === 'amber'
      ? 'rgba(255, 184, 77, 0.28)'
      : tone === 'red'
        ? 'rgba(255, 107, 107, 0.28)'
        : 'rgba(148, 163, 184, 0.24)',
  background: tone === 'teal'
    ? 'rgba(45, 212, 191, 0.10)'
    : tone === 'amber'
      ? 'rgba(255, 184, 77, 0.10)'
      : tone === 'red'
        ? 'rgba(255, 107, 107, 0.10)'
        : 'rgba(148, 163, 184, 0.10)',
  color: tone === 'teal'
    ? 'var(--teal, #2dd4bf)'
    : tone === 'amber'
      ? 'var(--warning, #ffb84d)'
      : tone === 'red'
        ? 'var(--error, #ff6b6b)'
        : 'var(--text-muted)',
}) as const;

function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `$${value}`;
}

function humanizeCode(value: string | number | null | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  return raw.replace(/[_./:-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function fmtList(items: string[] | undefined, emptyKey: string, formatter: (item: string) => string = (item) => item): string {
  if (!items || items.length === 0) return (t as any)(emptyKey);
  return items.map((item) => formatter(item)).join(', ');
}

function formatIdentityMode(value?: string | null): string {
  const key = String(value || '').trim();
  if (!key) return '—';
  const map: Record<string, string> = {
    service_account: 'service account',
    instance_identity: 'instance identity',
    anonymous_readonly: 'read only',
    delegated_user: 'delegated user',
  };
  return humanizeCode(map[key] || key);
}

function formatAuditStatus(value?: string | null): string {
  const key = String(value || '').trim();
  if (!key) return 'unknown';
  const map: Record<string, string> = {
    ok: 'allowed',
    denied: 'blocked',
    warning: 'warning',
    error: 'error',
  };
  return humanizeCode(map[key] || key);
}

function formatProfileName(profile: GovernanceProfile): string {
  return profile.description || humanizeCode(profile.name);
}

export function GovernanceTab({
  configGovernance,
  data,
  loading,
  busy,
  error,
  onToggleGlobalKillSwitch,
}: {
  configGovernance?: Record<string, any> | null;
  data?: GovernancePayload | null;
  loading: boolean;
  busy: boolean;
  error?: string | null;
  onToggleGlobalKillSwitch: () => void;
}) {
  if (loading && !data) {
    return <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-ui)' }}>{t('loading_configs')}</div>;
  }

  const overview = data?.overview || {};
  const capabilitySummary = overview.capabilities || {};
  const killSwitch = data?.kill_switch || {};
  const secretProfiles = data?.secret_profiles || [];
  const sandboxProfiles = data?.sandbox_profiles || [];
  const audit = data?.recent_audit || [];
  const identityDefaults = overview.identity_defaults || {};
  const budgets = overview.budgets || {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {error ? (
        <div style={{ ...cardStyle, borderColor: 'rgba(255, 107, 107, 0.28)', background: 'rgba(255, 107, 107, 0.08)', color: 'var(--error)' }}>
          {error}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
        <div style={cardStyle}>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', marginBottom: '8px' }}>{t('governance_status')}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={pill(overview.enabled === false ? 'red' : 'teal')}>
              {overview.enabled === false ? t('governance_disabled') : t('governance_enabled')}
            </span>
            <span style={pill(killSwitch.global ? 'red' : 'slate')}>
              {killSwitch.global ? t('governance_kill_switch_on') : t('governance_kill_switch_off')}
            </span>
          </div>
          <div style={{ marginTop: '10px', fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            <div>{t('governance_autonomy_cap')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{humanizeCode(overview.default_autonomy_cap || '—')}</span></div>
            <div>{t('governance_token_ttl')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{overview.token_ttl_seconds ?? '—'}s</span></div>
          </div>
        </div>

        <div style={cardStyle}>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', marginBottom: '8px' }}>{t('governance_capabilities')}</div>
          <div style={statValueStyle}>{capabilitySummary.total ?? 0}</div>
          <div style={{ marginTop: '10px', fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            <div>{t('governance_enabled_count')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{capabilitySummary.enabled_count ?? 0}</span></div>
            <div>{t('governance_disabled_count')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{capabilitySummary.disabled_count ?? 0}</span></div>
          </div>
        </div>

        <div style={cardStyle}>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', marginBottom: '8px' }}>{t('governance_profiles')}</div>
          <div style={statValueStyle}>{secretProfiles.length + sandboxProfiles.length}</div>
          <div style={{ marginTop: '10px', fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            <div>{t('governance_secret_profiles')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{secretProfiles.length}</span></div>
            <div>{t('governance_sandbox_profiles')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{sandboxProfiles.length}</span></div>
          </div>
        </div>

        <div style={cardStyle}>
          <div style={{ fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', marginBottom: '8px' }}>{t('governance_budget_defaults')}</div>
          <div style={{ marginTop: '2px', fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            <div>{t('governance_task_budget')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{fmtMoney(budgets.default_task_usd)}</span></div>
            <div>{t('governance_platform_budget')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{fmtMoney(budgets.platform_daily_usd)}</span></div>
            <div>{t('governance_tenant_budget')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{fmtMoney(budgets.tenant_daily_usd)}</span></div>
          </div>
        </div>
      </div>

      <div style={{ ...cardStyle, display: 'grid', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '6px' }}>{t('governance_kill_switch_title')}</div>
            <div style={{ fontSize: '15px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('governance_kill_switch_note')}</div>
          </div>
          <button
            onClick={onToggleGlobalKillSwitch}
            disabled={busy}
            style={{
              padding: '8px 14px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: killSwitch.global ? 'rgba(255, 107, 107, 0.14)' : 'rgba(45, 212, 191, 0.10)',
              color: killSwitch.global ? 'var(--error)' : 'var(--teal, #2dd4bf)',
              fontFamily: 'var(--font-ui)',
              fontSize: '15px',
              cursor: busy ? 'wait' : 'pointer',
            }}
          >
            {busy ? t('task_action_running') : (killSwitch.global ? t('governance_disable_kill_switch') : t('governance_enable_kill_switch'))}
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '15px', color: 'var(--text-muted)', marginBottom: '6px', fontFamily: 'var(--font-ui)' }}>{t('governance_kill_switch_epoch')}</div>
            <div style={{ fontFamily: 'var(--font-ui)', color: 'var(--text-primary)' }}>{killSwitch.epoch ?? 0}</div>
          </div>
          <div>
            <div style={{ fontSize: '15px', color: 'var(--text-muted)', marginBottom: '6px', fontFamily: 'var(--font-ui)' }}>{t('governance_kill_switch_categories')}</div>
            <div style={{ fontFamily: 'var(--font-ui)', color: 'var(--text-primary)' }}>{killSwitch.counts?.categories ?? 0}</div>
          </div>
          <div>
            <div style={{ fontSize: '15px', color: 'var(--text-muted)', marginBottom: '6px', fontFamily: 'var(--font-ui)' }}>{t('governance_kill_switch_capabilities')}</div>
            <div style={{ fontFamily: 'var(--font-ui)', color: 'var(--text-primary)' }}>{killSwitch.counts?.capabilities ?? 0}</div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
        <div style={cardStyle}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '10px' }}>{t('governance_unbound_summary')}</div>
          <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <div>{t('governance_unbound_secret_count')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{capabilitySummary.unbound_secret_count ?? 0}</span></div>
            <div>{t('governance_unbound_sandbox_count')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{capabilitySummary.unbound_sandbox_count ?? 0}</span></div>
          </div>
          <div style={{ marginTop: '10px', fontSize: '15px', color: 'var(--text-muted)', lineHeight: 1.7 }}>
            <div>{t('governance_unbound_secret_capabilities')}: <span style={{ color: 'var(--text-primary)' }}>{fmtList(capabilitySummary.unbound_secret_capabilities, 'governance_none', humanizeCode)}</span></div>
            <div>{t('governance_unbound_sandbox_capabilities')}: <span style={{ color: 'var(--text-primary)' }}>{fmtList(capabilitySummary.unbound_sandbox_capabilities, 'governance_none', humanizeCode)}</span></div>
          </div>
        </div>

        <div style={cardStyle}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '10px' }}>{t('governance_identity_defaults')}</div>
          <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <div>{t('governance_interactive_identity')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{formatIdentityMode(identityDefaults.interactive)}</span></div>
            <div>{t('governance_automation_identity')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{formatIdentityMode(identityDefaults.automation)}</span></div>
            <div>{t('governance_capability_overrides')}: <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-ui)' }}>{Object.keys(configGovernance?.capability_overrides || {}).length}</span></div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
        <div style={cardStyle}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '10px' }}>{t('governance_secret_profiles')}</div>
          {secretProfiles.length === 0 ? (
            <div style={{ fontSize: '15px', color: 'var(--text-muted)' }}>{t('governance_no_secret_profiles')}</div>
          ) : secretProfiles.map((profile) => (
            <div key={profile.name} style={{ padding: '10px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center', marginBottom: '4px' }}>
                <div style={{ color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{formatProfileName(profile)}</div>
                <span style={pill(profile.configured ? 'teal' : 'amber')}>{profile.configured ? t('governance_profile_ready') : t('governance_profile_needs_setup')}</span>
              </div>
              <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                <div>{t('governance_profile_kind')}: {humanizeCode(profile.kind || 'generic')}</div>
                <div>{t('governance_profile_fields')}: {profile.field_count ?? profile.fields?.length ?? 0}</div>
                <div>{t('governance_bound_capabilities')}: {profile.bound_capabilities?.length || 0}</div>
                {profile.description ? <div>{profile.description}</div> : null}
              </div>
            </div>
          ))}
        </div>

        <div style={cardStyle}>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '10px' }}>{t('governance_sandbox_profiles')}</div>
          {sandboxProfiles.length === 0 ? (
            <div style={{ fontSize: '15px', color: 'var(--text-muted)' }}>{t('governance_no_sandbox_profiles')}</div>
          ) : sandboxProfiles.map((profile) => (
            <div key={profile.name} style={{ padding: '10px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center', marginBottom: '4px' }}>
                <div style={{ color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{formatProfileName(profile)}</div>
                <span style={pill(profile.configured ? 'teal' : 'amber')}>{profile.configured ? t('governance_profile_ready') : t('governance_profile_needs_setup')}</span>
              </div>
              <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                <div>{t('governance_bound_capabilities')}: {profile.bound_capabilities?.length || 0}</div>
                <div>{t('governance_allowed_domains')}: {fmtList(profile.allowed_domains, 'governance_none')}</div>
                <div>{t('governance_allowed_paths')}: {fmtList(profile.allowed_paths, 'governance_none')}</div>
                <div>{t('governance_blocked_commands')}: {fmtList(profile.blocked_commands, 'governance_none', humanizeCode)}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={cardStyle}>
        <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--accent)', marginBottom: '10px' }}>{t('governance_recent_audit')}</div>
        {audit.length === 0 ? (
          <div style={{ fontSize: '15px', color: 'var(--text-muted)' }}>{t('governance_no_audit_records')}</div>
        ) : audit.map((record, index) => (
          <div key={`${record.task_id || 'task'}-${record.capability_id || 'cap'}-${index}`} style={{ padding: '10px 0', borderTop: index === 0 ? 'none' : '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '4px' }}>
              <div style={{ color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{humanizeCode(record.capability_id || '—')}</div>
              <span style={pill(record.result_status === 'denied' ? 'red' : record.result_status === 'ok' ? 'teal' : 'amber')}>
                {formatAuditStatus(record.result_status)}
              </span>
            </div>
            <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              <div>{t('governance_audit_actor')}: <span style={{ color: 'var(--text-primary)' }}>{humanizeCode(record.actor_identity || '—')}</span></div>
              <div>{t('governance_audit_tool')}: <span style={{ color: 'var(--text-primary)' }}>{record.tool_name || '—'}</span></div>
              <div>{t('governance_audit_profiles')}: <span style={{ color: 'var(--text-primary)' }}>{fmtList([record.secret_profile || '—', record.sandbox_profile || '—'], 'governance_none', humanizeCode)}</span></div>
              <div>{t('governance_audit_warnings')}: <span style={{ color: 'var(--text-primary)' }}>{fmtList(record.warnings, 'governance_none', humanizeCode)}</span></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
