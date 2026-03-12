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
});
