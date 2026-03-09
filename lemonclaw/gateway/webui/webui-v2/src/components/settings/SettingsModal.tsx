import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';
import { MCPServersEditor } from './MCPServersEditor';
import { SkillsTab } from './SkillsTab';
import { SoulEditor } from './SoulEditor';
import { WhatsAppPairingCard } from './WhatsAppPairingCard';

type NoticeTone = 'info' | 'warning';
type DraftData = Record<string, any>;
type ToolStatusMap = Record<string, { installed: boolean; binary?: string }>;

const MOBILE_BREAKPOINT = 768;
const TABS = ['soul', 'providers', 'agents', 'channels', 'tools', 'skills'];

const noticeStyle = (tone: NoticeTone) => ({
  marginBottom: '12px',
  padding: '10px 12px',
  borderRadius: '6px',
  border: `1px solid ${tone === 'warning' ? 'rgba(255, 170, 0, 0.28)' : 'rgba(100, 149, 237, 0.28)'}`,
  background: tone === 'warning' ? 'rgba(255, 170, 0, 0.08)' : 'rgba(100, 149, 237, 0.08)',
  color: tone === 'warning' ? 'var(--warning, #ffb84d)' : 'var(--text-secondary)',
  fontFamily: 'var(--font-mono)',
  fontSize: '11px',
  lineHeight: 1.6,
}) as const;

const badgeStyle = (tone: 'teal' | 'amber' | 'slate') => ({
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  borderRadius: '999px',
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  lineHeight: 1.4,
  border: '1px solid',
  borderColor: tone === 'teal'
    ? 'rgba(45, 212, 191, 0.28)'
    : tone === 'amber'
      ? 'rgba(255, 184, 77, 0.28)'
      : 'rgba(148, 163, 184, 0.24)',
  background: tone === 'teal'
    ? 'rgba(45, 212, 191, 0.10)'
    : tone === 'amber'
      ? 'rgba(255, 184, 77, 0.10)'
      : 'rgba(148, 163, 184, 0.10)',
  color: tone === 'teal'
    ? 'var(--teal, #2dd4bf)'
    : tone === 'amber'
      ? 'var(--warning, #ffb84d)'
      : 'var(--text-muted)',
}) as const;

type ChannelBadge = { label: string; tone: 'teal' | 'amber' | 'slate' };

function getChannelBadges(channelKey: string): ChannelBadge[] {
  const autoPairing = { label: t('channel_badge_auto_pairing'), tone: 'teal' as const };
  const qrLogin = { label: t('channel_badge_requires_qr'), tone: 'amber' as const };
  const whitelistOnly = { label: t('channel_badge_whitelist_only'), tone: 'slate' as const };
  const manualApproval = { label: t('channel_badge_manual_approval'), tone: 'teal' as const };

  const map: Record<string, ChannelBadge[]> = {
    telegram: [autoPairing, manualApproval],
    discord: [autoPairing, manualApproval],
    whatsapp: [qrLogin, autoPairing, manualApproval],
    slack: [autoPairing, manualApproval],
    feishu: [autoPairing, manualApproval],
    matrix: [autoPairing, manualApproval],
    wecom: [whitelistOnly],
    dingtalk: [whitelistOnly],
    qq: [whitelistOnly],
    email: [whitelistOnly],
    mochat: [whitelistOnly],
  };

  return map[channelKey] || [];
}

function isGroup(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getNestedValue(data: DraftData, path: string): any {
  return path.split('.').reduce<any>((current, key) => current?.[key], data);
}

function normalizeChangedPath(path: string[]): string {
  if (path[0] === 'agents' && path[1] === 'defaults') {
    return `agents.defaults.${path[2]}`;
  }
  if (path[0] === 'channels') {
    return `channels.${path[1]}`;
  }
  if (path[0] === 'providers') {
    return `providers.${path[1]}`;
  }
  if (path[0] === 'tools') {
    if (path[1] === 'mcp_servers') {
      return `tools.${path[1]}`;
    }
    if (path[1] === 'browser' || path[1] === 'coding') {
      return `tools.${path[1]}`;
    }
    if (path[1] === 'exec' && path[2]) {
      return `tools.exec.${path[2]}`;
    }
    if (path[1] === 'web' && path[2] === 'search' && path[3]) {
      return `tools.web.search.${path[3]}`;
    }
  }
  return path.join('.');
}

function humanizeLabel(key: string): string {
  return key.replaceAll('.', ' / ').replaceAll('_', ' ');
}

function omitKeys<T extends Record<string, any>>(value: T | null | undefined, keys: string[]): T | null {
  if (!value) return null;
  const clone: Record<string, any> = { ...value };
  for (const key of keys) delete clone[key];
  return clone as T;
}

const HIDDEN_AGENT_DEFAULT_KEYS = ['workspace', 'input_cost_per_1k_tokens', 'output_cost_per_1k_tokens'];

const FIELD_HELP_KEYS: Record<string, string> = {
  'agents.defaults.model': 'settings_help_model',
  'agents.defaults.provider': 'settings_help_provider',
  'agents.defaults.temperature': 'settings_help_temperature',
  'agents.defaults.max_tokens': 'settings_help_max_tokens',
  'agents.defaults.timezone': 'settings_help_timezone',
  'agents.defaults.memory_window': 'settings_help_memory_window',
  'agents.defaults.max_tool_iterations': 'settings_help_max_tool_iterations',
  'agents.defaults.token_budget_per_session': 'settings_help_token_budget_per_session',
  'agents.defaults.cost_budget_per_day': 'settings_help_cost_budget_per_day',
  'agents.defaults.system_prompt': 'settings_help_system_prompt',
  'agents.defaults.disabled_skills': 'settings_help_disabled_skills',
  'channels.send_progress': 'settings_help_send_progress',
  'channels.send_tool_hints': 'settings_help_send_tool_hints',
  'channels.auto_pairing': 'settings_help_auto_pairing',
  'tools.web.search.api_key': 'settings_help_search_api_key',
  'tools.web.search.max_results': 'settings_help_search_max_results',
  'tools.browser.timeout': 'settings_help_browser_timeout',
  'tools.browser.allowed_domains': 'settings_help_browser_allowed_domains',
  'tools.browser.headed': 'settings_help_browser_headed',
  'tools.browser.content_boundaries': 'settings_help_browser_content_boundaries',
  'tools.browser.max_output': 'settings_help_browser_max_output',
  'tools.coding.enabled': 'settings_help_coding_enabled',
  'tools.coding.timeout': 'settings_help_coding_timeout',
  'tools.coding.api_key': 'settings_help_coding_api_key',
  'tools.coding.api_base': 'settings_help_coding_api_base',
  'tools.exec.timeout': 'settings_help_exec_timeout',
  'tools.exec.path_append': 'settings_help_exec_path_append',
};

const FIELD_PLACEHOLDERS: Record<string, string> = {
  'agents.defaults.provider': 'auto',
  'agents.defaults.timezone': 'Asia/Shanghai',
  'agents.defaults.disabled_skills': 'skill-a, skill-b',
  'tools.browser.allowed_domains': '*.example.com, api.example.com',
  'tools.coding.api_base': 'https://api.example.com',
  'tools.exec.path_append': '/usr/local/bin:/app/.venv/bin',
};

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [draft, setDraft] = useState<DraftData | null>(null);
  const [toolStatus, setToolStatus] = useState<ToolStatusMap | null>(null);
  const [changedPaths, setChangedPaths] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState('soul');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const copyResetTimer = useRef<number | null>(null);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
      }
    };
    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
  }, []);

  const load = async () => {
    try {
      const res = await apiFetch('/api/settings');
      const data = await res.json();
      setDraft(JSON.parse(JSON.stringify(data.settings)));
      setToolStatus(data.tool_status || null);
      setChangedPaths(new Set());
    } catch (e) {
      console.error('Failed to load settings', e);
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => () => {
    if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
  }, []);

  const handleChange = (path: string[], value: any) => {
    if (!draft) return;
    let obj: DraftData = draft;
    for (let i = 0; i < path.length - 1; i++) {
      if (!obj[path[i]]) obj[path[i]] = {};
      obj = obj[path[i]];
    }
    obj[path[path.length - 1]] = value;
    setDraft({ ...draft });
    const changedPath = normalizeChangedPath(path);
    setChangedPaths((prev) => new Set(prev).add(changedPath));
  };

  const handleSave = async () => {
    if (!draft || changedPaths.size === 0) return onClose();
    setSaveError(null);

    const payload: Record<string, any> = {};
    for (const path of Array.from(changedPaths)) {
      payload[path] = getNestedValue(draft, path);
    }

    try {
      await apiFetch('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) });
      const applyRes = await apiFetch('/api/settings/apply', {
        method: 'POST',
        body: JSON.stringify({ changed_paths: Array.from(changedPaths) }),
      });
      const applyData = await applyRes.json();
      if (applyData.restart_required) {
        console.log('Backend is restarting to apply changes.');
      }
      onClose();
    } catch (e: any) {
      setSaveError(e.message || 'Save failed');
    }
  };

  const handleClose = () => {
    if (changedPaths.size > 0 && !confirm(t('confirm_discard_changes'))) return;
    onClose();
  };

  const renderNotice = (message: string, tone: NoticeTone = 'info') => (
    <div style={noticeStyle(tone)}>{message}</div>
  );

  const copyValue = async (fieldPath: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(fieldPath);
      if (copyResetTimer.current) window.clearTimeout(copyResetTimer.current);
      copyResetTimer.current = window.setTimeout(() => setCopiedField((current) => current === fieldPath ? null : current), 1800);
    } catch (err) {
      console.error('Copy failed', err);
    }
  };

  const displayLabel = (key: string): string => {
    if (key === 'browser') return t('tools_browser_title');
    if (key === 'coding') return t('tools_coding_title');
    if (key === 'web.search') return t('tools_web_search_title');
    if (key === 'exec') return t('tools_exec_title');
    if (key === 'mcp_servers') return t('mcp_servers_title');
    return humanizeLabel(key);
  };

  const activeTabData = draft?.[activeTab];
  const settingsDescKey = `settings_desc_${activeTab}` as keyof any;
  const settingsDesc = (t as any)(settingsDescKey) || t('settings_desc');
  const getFieldHelp = (fullPath: string): string | null => {
    const specificKey = FIELD_HELP_KEYS[fullPath];
    if (specificKey) {
      const value = (t as any)(specificKey);
      if (value && value !== specificKey) return value;
    }

    const last = fullPath.split('.').pop() || '';
    const genericMap: Record<string, string> = {
      enabled: 'settings_help_generic_enabled',
      api_key: 'settings_help_generic_api_key',
      api_base: 'settings_help_generic_api_base',
      base_url: 'settings_help_generic_url',
      url: 'settings_help_generic_url',
      token: 'settings_help_generic_token',
      bot_token: 'settings_help_generic_token',
      app_token: 'settings_help_generic_token',
      access_token: 'settings_help_generic_token',
      client_secret: 'settings_help_generic_secret',
      app_secret: 'settings_help_generic_secret',
      timeout: 'settings_help_generic_timeout',
      tool_timeout: 'settings_help_generic_timeout',
      connect_timeout_ms: 'settings_help_generic_timeout_ms',
      watch_timeout_ms: 'settings_help_generic_timeout_ms',
      reply_delay_ms: 'settings_help_generic_timeout_ms',
      refresh_interval_ms: 'settings_help_generic_interval_ms',
      socket_reconnect_delay_ms: 'settings_help_generic_interval_ms',
      socket_max_reconnect_delay_ms: 'settings_help_generic_interval_ms',
      allow_from: 'settings_help_generic_allow_from',
      trusted_proxies: 'settings_help_generic_allow_from',
      command: 'settings_help_generic_command',
      args: 'settings_help_generic_args',
      env: 'settings_help_generic_env',
      headers: 'settings_help_generic_headers',
      proxy: 'settings_help_generic_proxy',
      mode: 'settings_help_generic_mode',
      policy: 'settings_help_generic_policy',
      webhook_path: 'settings_help_generic_path',
      socket_path: 'settings_help_generic_path',
      sessions: 'settings_help_generic_list',
      panels: 'settings_help_generic_list',
    };
    const key = genericMap[last];
    if (!key) return t('settings_help_generic_fallback');
    const value = (t as any)(key);
    return value && value !== key ? value : t('settings_help_generic_fallback');
  };

  const getFieldPlaceholder = (fullPath: string): string => {
    if (FIELD_PLACEHOLDERS[fullPath]) return FIELD_PLACEHOLDERS[fullPath];
    const last = fullPath.split('.').pop() || '';
    const genericMap: Record<string, string> = {
      api_base: 'https://api.example.com',
      base_url: 'https://example.com',
      url: 'https://example.com',
      allow_from: 'user1, user2',
      trusted_proxies: '127.0.0.1, 10.0.0.0/8',
      command: 'npx',
      args: 'arg1, arg2',
      proxy: 'http://127.0.0.1:7890',
      webhook_path: '/webhook/path',
      socket_path: '/socket.io',
      sessions: 'session-a, session-b',
      panels: 'panel-a, panel-b',
    };
    return genericMap[last] || '';
  };

  const contentData = activeTab === 'agents'
    ? { ...activeTabData, defaults: omitKeys(activeTabData?.defaults, HIDDEN_AGENT_DEFAULT_KEYS) }
    : activeTab === 'tools'
      ? activeTabData
      : activeTabData;
  const dataKeys = activeTab !== 'skills' && contentData
    ? Object.keys(contentData).filter((key) => isGroup(contentData[key]))
    : [];
  // Prepend tool status card for the tools tab
  const quickJumpKeys = activeTab === 'tools'
    ? ['_tool_status', ...dataKeys]
    : dataKeys;

  const renderWorkspaceCard = () => {
    if (!draft?.agents?.defaults?.workspace) return null;
    return (
      <div style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: isMobile ? '12px' : '16px' }}>
        <div style={{ fontSize: isMobile ? '13px' : '14px', color: 'var(--accent)', marginBottom: '10px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--purple)' }}>#</span> {t('settings_workspace_readonly_title')}
        </div>
        <div style={{ marginBottom: '10px', padding: '10px 12px', borderRadius: '6px', background: 'var(--bg-primary)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
          {draft.agents.defaults.workspace}
        </div>
        {renderNotice(t('settings_workspace_readonly_note'), 'info')}
      </div>
    );
  };

  const renderToolStatusCard = () => {
    if (!draft?.tools) return null;
    const browserInstalled = Boolean(toolStatus?.browser?.installed);
    const codingInstalled = Boolean(toolStatus?.coding?.installed);
    const rows: Array<{ id: string; title: string; enabled: boolean; installed: boolean; binary: string; warning: boolean }> = [
      {
        id: 'browser',
        title: t('tool_status_browser_title'),
        enabled: Boolean(draft.tools.browser?.enabled),
        installed: browserInstalled,
        binary: toolStatus?.browser?.binary || '',
        warning: draft.tools.browser?.enabled && !browserInstalled,
      },
      {
        id: 'coding',
        title: t('tool_status_coding_title'),
        enabled: Boolean(draft.tools.coding?.enabled),
        installed: codingInstalled,
        binary: toolStatus?.coding?.binary || '',
        warning: draft.tools.coding?.enabled && !codingInstalled,
      },
    ];

    return (
      <div id="setting-group-_tool_status" style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: isMobile ? '12px' : '16px' }}>
        <div style={{ fontSize: isMobile ? '13px' : '14px', color: 'var(--accent)', marginBottom: '10px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--purple)' }}>#</span> {t('tool_status_title')}
        </div>
        {rows.map((row) => (
          <div key={row.id} style={{ padding: '10px 0', borderTop: row.id === 'browser' ? 'none' : '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-primary)' }}>{row.title}</div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <span style={{ padding: '2px 6px', borderRadius: '999px', fontFamily: 'var(--font-mono)', fontSize: '10px', background: row.enabled ? 'rgba(76, 175, 80, 0.15)' : 'var(--bg-primary)', color: row.enabled ? 'var(--success)' : 'var(--text-muted)', border: '1px solid var(--border)' }}>
                  {row.enabled ? t('tool_status_enabled') : t('tool_status_disabled')}
                </span>
                <span style={{ padding: '2px 6px', borderRadius: '999px', fontFamily: 'var(--font-mono)', fontSize: '10px', background: row.installed ? 'rgba(76, 175, 80, 0.15)' : 'rgba(255, 68, 68, 0.12)', color: row.installed ? 'var(--success)' : 'var(--error)', border: '1px solid var(--border)' }}>
                  {row.installed ? t('tool_status_installed') : t('tool_status_missing')}
                </span>
              </div>
            </div>
            {row.installed && row.binary ? (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>
                {t('tool_status_binary_label')}: {row.binary}
              </div>
            ) : row.warning ? (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--error)' }}>
                {t('tool_status_missing_note')}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    );
  };

  const renderFields = (data: any, path: string[]): any => {
    if (!data) return null;

    return Object.entries(data).map(([k, v]) => {
      const currentPath = [...path, k];
      const fullPath = currentPath.join('.');

      if (k === 'mcp_servers' && isGroup(v)) {
        return (
          <MCPServersEditor key={k} servers={v as Record<string, any>} onChange={(newVal) => handleChange(currentPath, newVal)} />
        );
      }

      if (Array.isArray(v)) {
        return (
          <div key={fullPath} style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{displayLabel(k)}</label>
            {getFieldHelp(fullPath) && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px', lineHeight: 1.5 }}>{getFieldHelp(fullPath)}</div>}
            <input type="text" placeholder={getFieldPlaceholder(fullPath)} value={v.join(', ')} onInput={(e) => handleChange(currentPath, (e.target as HTMLInputElement).value.split(',').map((s: string) => s.trim()).filter(Boolean))} style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }} />
          </div>
        );
      }

      if (isGroup(v)) {
        let currentObj: any = v;
        let displayKey = k;
        const cPath = [...currentPath];
        while (isGroup(currentObj)) {
          const keys = Object.keys(currentObj);
          if (keys.length === 1 && isGroup(currentObj[keys[0]])) {
            displayKey += `.${keys[0]}`;
            cPath.push(keys[0]);
            currentObj = currentObj[keys[0]];
          } else {
            break;
          }
        }

        return (
          <div id={`setting-group-${displayKey}`} key={displayKey} style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: isMobile ? '12px' : '16px' }}>
            <div style={{ marginBottom: '16px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
              <div style={{ fontSize: isMobile ? '13px' : '14px', color: 'var(--accent)', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px', overflowWrap: 'anywhere' }}>
                <span style={{ color: 'var(--purple)' }}>#</span> {displayLabel(displayKey)}
              </div>
              {path[0] === 'channels' && getChannelBadges(displayKey).length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
                  {getChannelBadges(displayKey).map((badge) => (
                    <span key={`${displayKey}-${badge.label}`} style={badgeStyle(badge.tone)}>
                      {badge.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {path[0] === 'tools' && displayKey === 'web.search' && renderNotice(t('web_search_provider_note'), 'info')}
            {path[0] === 'tools' && displayKey === 'coding' && renderNotice(t('coding_provider_note'), 'info')}
            {renderFields(currentObj, cPath)}
            {path[0] === 'channels' && displayKey === 'whatsapp' && (
              <WhatsAppPairingCard
                enabled={Boolean((currentObj as any).enabled)}
                dirty={changedPaths.has('channels.whatsapp')}
              />
            )}
          </div>
        );
      }

      if (typeof v === 'boolean') {
        return (
          <div key={fullPath} style={{ marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input type="checkbox" checked={v} onChange={(e) => handleChange(currentPath, (e.target as HTMLInputElement).checked)} />
              <label style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{displayLabel(k)}</label>
            </div>
            {getFieldHelp(fullPath) && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px', lineHeight: 1.5 }}>{getFieldHelp(fullPath)}</div>}
          </div>
        );
      }

      if (typeof v === 'number') {
        return (
          <div key={fullPath} style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{displayLabel(k)}</label>
            {getFieldHelp(fullPath) && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px', lineHeight: 1.5 }}>{getFieldHelp(fullPath)}</div>}
            <input type="number" placeholder={getFieldPlaceholder(fullPath)} value={v as number} onInput={(e) => handleChange(currentPath, Number((e.target as HTMLInputElement).value))} style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }} />
          </div>
        );
      }

      const help = getFieldHelp(fullPath);
      const commonLabel = <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{displayLabel(k)}</label>;
      const helpText = help ? <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px', lineHeight: 1.5 }}>{help}</div> : null;

      // Auto-generated readonly fields with copy button (Feishu encrypt_key, verification_token)
      if ((k === 'encrypt_key' || k === 'verification_token') && path.includes('feishu')) {
        const val = String(v ?? '');
        const fieldLabel = k === 'encrypt_key' ? 'Encrypt Key' : 'Verification Token';
        const feishuTarget = k === 'encrypt_key' ? 'Encrypt Key' : 'Verification Token';
        return (
          <div key={fullPath} style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{fieldLabel}</label>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px', lineHeight: 1.5 }}>
              {t('feishu_token_help').replace('{target}', feishuTarget)}
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <input type="text" readOnly value={val} style={{ flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box', opacity: 0.8 }} />
              <button
                onClick={() => { void copyValue(fullPath, val); }}
                style={{ padding: '8px 12px', background: copiedField === fullPath ? 'rgba(45, 212, 191, 0.14)' : 'var(--bg-tertiary)', border: '1px solid var(--border)', color: copiedField === fullPath ? 'var(--teal)' : 'var(--accent)', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                {copiedField === fullPath ? t('copied') : t('copy')}
              </button>
            </div>
          </div>
        );
      }

      if (fullPath === 'agents.defaults.system_prompt') {
        return (
          <div key={fullPath} style={{ marginBottom: '12px' }}>
            {commonLabel}
            {helpText}
            <textarea value={String(v ?? '')} placeholder={getFieldPlaceholder(fullPath)} onInput={(e) => handleChange(currentPath, (e.target as HTMLTextAreaElement).value)} style={{ width: '100%', minHeight: '120px', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '10px 12px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box', resize: 'vertical' }} />
          </div>
        );
      }
      return (
        <div key={fullPath} style={{ marginBottom: '12px' }}>
          {commonLabel}
          {helpText}
          <input type="text" placeholder={getFieldPlaceholder(fullPath)} value={String(v ?? '')} onInput={(e) => handleChange(currentPath, (e.target as HTMLInputElement).value)} style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box' }} />
        </div>
      );
    });
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999, display: 'flex', alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'center', padding: isMobile ? '0' : '24px', backdropFilter: 'blur(4px)' }}>
      <div style={{ width: '100%', maxWidth: isMobile ? '100%' : '1100px', height: isMobile ? '100dvh' : '85vh', background: 'var(--bg-secondary)', border: isMobile ? 'none' : '1px solid var(--border)', borderRadius: isMobile ? '0' : '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: isMobile ? 'none' : '0 20px 60px rgba(0,0,0,0.6)' }}>
        <div style={{ padding: isMobile ? '14px 16px' : '16px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: isMobile ? '14px' : '16px', color: 'var(--text-primary)', letterSpacing: '1px', minWidth: 0 }}><span style={{ color: 'var(--purple)' }}>//</span> {t('settings_title')}</div>
          <button onClick={handleClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '24px', cursor: 'pointer', lineHeight: 1, flexShrink: 0 }}>×</button>
        </div>

        <div style={{ display: 'flex', flex: 1, minHeight: 0, flexDirection: isMobile ? 'column' : 'row' }}>
          <div style={{ width: isMobile ? '100%' : '200px', minWidth: isMobile ? '100%' : '200px', maxWidth: '100%', borderRight: isMobile ? 'none' : '1px solid var(--border)', borderBottom: isMobile ? '1px solid var(--border)' : 'none', display: 'flex', flexDirection: isMobile ? 'row' : 'column', gap: '6px', padding: isMobile ? '12px 12px 8px' : '16px', overflowX: isMobile ? 'auto' : 'visible', overflowY: 'hidden', scrollbarWidth: 'none' }}>
            {TABS.map((tab) => (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{ textAlign: 'left', padding: '10px 12px', minWidth: isMobile ? 'max-content' : 'auto', background: activeTab === tab ? 'var(--bg-tertiary)' : 'transparent', color: activeTab === tab ? 'var(--accent)' : 'var(--text-muted)', border: '1px solid', borderColor: activeTab === tab ? 'var(--border)' : 'transparent', borderRadius: '6px', fontFamily: 'var(--font-mono)', fontSize: isMobile ? '11px' : '12px', textTransform: 'uppercase', cursor: 'pointer', transition: 'all 0.2s', flexShrink: 0, whiteSpace: 'nowrap' }}>
                {(t as any)(`tab_${tab}`)}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, minWidth: 0, padding: isMobile ? '16px' : '32px', overflowY: 'auto', background: 'var(--bg-primary)', display: 'flex', gap: isMobile ? '0' : '24px', alignItems: 'flex-start' }}>
            {activeTab === 'soul' ? (
              <div style={{ flex: 1, minWidth: 0, animation: 'fadeIn 0.3s ease-out' }}><SoulEditor /></div>
            ) : !draft ? <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('loading_configs')}</div> : (
              <>
                <div style={{ flex: 1, minWidth: 0, animation: 'fadeIn 0.3s ease-out' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: isMobile ? '18px' : '20px', color: 'var(--text-primary)', marginBottom: '8px', textTransform: 'capitalize', overflowWrap: 'anywhere' }}>
                    {(t as any)(`tab_${activeTab}`)}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: isMobile ? '20px' : '32px' }}>{settingsDesc}</div>

                  {activeTab === 'agents' && renderWorkspaceCard()}
                  {activeTab === 'tools' && renderToolStatusCard()}
                  {activeTab === 'skills' ? <SkillsTab /> : renderFields(contentData, [activeTab])}
                </div>

                {!isMobile && activeTab !== 'skills' && quickJumpKeys.length > 0 && (
                  <div style={{ width: '160px', flexShrink: 0, position: 'sticky', top: '0', display: 'flex', flexDirection: 'column', gap: '6px', animation: 'fadeIn 0.3s ease-out' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '8px', letterSpacing: '1px' }}>// QUICK JUMP</div>
                    {quickJumpKeys.map((key) => {
                      // Special cards rendered outside contentData
                      const isSpecial = key.startsWith('_');
                      const isEnabled = isSpecial ? undefined : contentData?.[key]?.enabled;
                      let displayKey = key;
                      if (!isSpecial) {
                        let obj = contentData?.[key];
                        while (isGroup(obj)) {
                          const keys = Object.keys(obj);
                          if (keys.length === 1 && isGroup(obj[keys[0]])) {
                            displayKey += `.${keys[0]}`;
                            obj = obj[keys[0]];
                          } else {
                            break;
                          }
                        }
                      }
                      const label = key === '_tool_status' ? t('tool_status_title') : displayLabel(displayKey);
                      return (
                        <button key={key} onClick={() => document.getElementById(`setting-group-${displayKey}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })} style={{ textAlign: 'left', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px', padding: '6px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '6px', color: isEnabled === false ? 'var(--error)' : (isEnabled ? 'var(--success)' : 'var(--text-primary)'), background: isEnabled === false ? 'rgba(255, 68, 68, 0.1)' : (isEnabled ? 'rgba(76, 175, 80, 0.1)' : 'var(--bg-secondary)'), border: '1px solid', borderColor: isEnabled === false ? 'rgba(255, 68, 68, 0.2)' : (isEnabled ? 'rgba(76, 175, 80, 0.2)' : 'var(--border)'), transition: 'all 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.filter = 'brightness(1.2)'} onMouseLeave={(e) => e.currentTarget.style.filter = 'none'}>
                          <span style={{ opacity: 0.5 }}>#</span> {label}
                        </button>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div style={{ padding: isMobile ? '12px 16px calc(12px + env(safe-area-inset-bottom))' : '16px 24px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', gap: '12px', background: 'var(--bg-secondary)', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'stretch' : 'center' }}>
          <div style={{ flex: isMobile ? '0 0 auto' : 1, display: 'flex', alignItems: 'center', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', minHeight: '16px' }}>
            {changedPaths.size > 0 && <span style={{ color: 'var(--accent)' }}>● {changedPaths.size} {t('unsaved_changes')}</span>}
            {saveError && <span style={{ color: 'var(--error)', marginLeft: changedPaths.size > 0 ? '8px' : '0' }}>{saveError}</span>}
          </div>
          <div style={{ display: 'flex', gap: '12px', width: isMobile ? '100%' : 'auto' }}>
            <button onClick={handleClose} style={{ padding: '10px 24px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-primary)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', flex: isMobile ? 1 : '0 0 auto' }}>{t('btn_cancel')}</button>
            <button onClick={handleSave} disabled={changedPaths.size === 0} style={{ padding: '10px 24px', background: changedPaths.size === 0 ? 'var(--bg-tertiary)' : 'var(--accent)', border: 'none', borderRadius: '6px', color: '#fff', cursor: changedPaths.size === 0 ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 'bold', flex: isMobile ? 1 : '0 0 auto' }}>{t('btn_save_apply')}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
