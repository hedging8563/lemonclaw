import { beforeAll, describe, expect, it } from 'vitest';
import { h } from 'preact';
import render from 'preact-render-to-string';

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    },
    configurable: true,
  });
});

describe('normalizeChangedPath', () => {
  it('maps nested operator tool paths to safe writable roots', async () => {
    const { normalizeChangedPath } = await import('../src/components/settings/SettingsModal');
    expect(normalizeChangedPath(['tools', 'http', 'auth_profiles', 'svc', 'Authorization'])).toBe('tools.http');
    expect(normalizeChangedPath(['tools', 'db', 'sqlite_profiles', 'local'])).toBe('tools.db');
    expect(normalizeChangedPath(['tools', 'notify', 'allow_webhook_domains'])).toBe('tools.notify');
    expect(normalizeChangedPath(['tools', 'k8s', 'allowed_namespaces'])).toBe('tools.k8s');
  });
});

describe('operator settings editors', () => {
  it('renders HTTP auth profiles editor', async () => {
    const { HTTPAuthProfilesEditor } = await import('../src/components/settings/HTTPAuthProfilesEditor');
    const html = render(
      <HTTPAuthProfilesEditor
        profiles={{ support_api: { Authorization: 'Bear****oken', 'X-API-Key': 'abc1****6789' } }}
        onChange={() => undefined}
      />
    );
    expect(html).toContain('support_api');
    expect(html).toContain('HTTP Auth Profiles');
    expect(html).toMatchSnapshot();
  });

  it('renders SQLite profiles editor', async () => {
    const { SQLiteProfilesEditor } = await import('../src/components/settings/SQLiteProfilesEditor');
    const html = render(
      <SQLiteProfilesEditor
        profiles={{ local_cache: '/var/lib/lemonclaw/cache.db' }}
        onChange={() => undefined}
      />
    );
    expect(html).toContain('local_cache');
    expect(html).toContain('SQLite Profiles');
    expect(html).toMatchSnapshot();
  });

  it('renders PostgreSQL profiles editor', async () => {
    const { PostgresProfilesEditor } = await import('../src/components/settings/PostgresProfilesEditor');
    const html = render(
      <PostgresProfilesEditor
        profiles={{ analytics_ro: { host: 'db.example.internal', port: 5432, dbname: 'analytics', user: 'reader', password: '****', sslmode: 'require' } }}
        onChange={() => undefined}
      />
    );
    expect(html).toContain('analytics_ro');
    expect(html).toContain('PostgreSQL Profiles');
    expect(html).toMatchSnapshot();
  });

  it('renders governance overview tab', async () => {
    const { GovernanceTab } = await import('../src/components/settings/GovernanceTab');
    const html = render(
      <GovernanceTab
        configGovernance={{ capability_overrides: { 'exec.system': { approval_policy: 'require_confirm' } } }}
        data={{
          overview: {
            enabled: true,
            default_autonomy_cap: 'L1',
            token_ttl_seconds: 900,
            identity_defaults: { interactive: 'service_account', automation: 'instance_identity' },
            budgets: { default_task_usd: 2.5, platform_daily_usd: 50, tenant_daily_usd: 10 },
            capabilities: {
              total: 12,
              enabled_count: 11,
              disabled_count: 1,
              unbound_secret_count: 2,
              unbound_sandbox_count: 3,
              unbound_secret_capabilities: ['http.write'],
              unbound_sandbox_capabilities: ['exec.system'],
            },
          },
          secret_profiles: [{ name: 'ops-http', kind: 'headers', configured: true, field_count: 2, bound_capabilities: ['http.write'] }],
          sandbox_profiles: [{ name: 'runtime-default', allowed_domains: ['api.example.com'], allowed_paths: ['/workspace'], blocked_commands: ['rm -rf'], bound_capabilities: ['exec.system'] }],
          kill_switch: { global: false, epoch: 2, counts: { categories: 1, capabilities: 1 } },
          recent_audit: [{ capability_id: 'exec.system', result_status: 'ok', actor_identity: 'instance:test3', tool_name: 'exec', sandbox_profile: 'runtime-default', warnings: ['unbound_secret_profile'] }],
        }}
        loading={false}
        busy={false}
        error={null}
        onToggleGlobalKillSwitch={() => undefined}
      />
    );
    expect(html).toContain('Governance Status');
    expect(html).toContain('Kill Switch');
    expect(html).toContain('exec.system');
    expect(html).toMatchSnapshot();
  });
});
