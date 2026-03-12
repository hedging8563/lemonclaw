import { useEffect, useRef, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { dictToLines, editorStyles as S, linesToDict, MOBILE_BREAKPOINT, srOnly } from './SettingsEditorShared';

interface MCPServer {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  tool_timeout?: number;
}

interface Props {
  servers: Record<string, MCPServer>;
  onChange: (servers: Record<string, MCPServer>) => void;
}

function ExternalLinkButton({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      title={label}
      style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px', minHeight: '34px', padding: '0 14px', background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '6px', fontFamily: 'var(--font-mono)', fontSize: '12px', textDecoration: 'none', whiteSpace: 'nowrap' }}
    >
      <span>{label}</span>
      <span aria-hidden="true">↗</span>
    </a>
  );
}

function ServerCard({ name, server, onUpdate, onDelete }: {
  name: string;
  server: MCPServer;
  onUpdate: (s: MCPServer) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setModeState] = useState<'stdio' | 'http'>(server.url ? 'http' : 'stdio');
  const isHttp = mode === 'http';

  const [argsText, setArgsText] = useState((server.args || []).join(', '));
  const [envText, setEnvText] = useState(dictToLines(server.env));
  const [headersText, setHeadersText] = useState(dictToLines(server.headers));

  useEffect(() => { setArgsText((server.args || []).join(', ')); }, [JSON.stringify(server.args)]);
  useEffect(() => { setEnvText(dictToLines(server.env)); }, [JSON.stringify(server.env)]);
  useEffect(() => { setHeadersText(dictToLines(server.headers)); }, [JSON.stringify(server.headers)]);

  const setMode = (m: 'stdio' | 'http') => {
    setModeState(m);
    if (m === 'http') {
      onUpdate({ url: server.url || '', headers: server.headers || {}, tool_timeout: server.tool_timeout ?? 30 });
    } else {
      onUpdate({ command: server.command || '', args: server.args || [], env: server.env || {}, tool_timeout: server.tool_timeout ?? 30 });
    }
  };

  const summary = isHttp
    ? (server.url || t('mcp_summary_no_url'))
    : (server.command ? `${server.command} ${(server.args || []).join(' ')}` : t('mcp_summary_no_command'));

  return (
    <div style={S.card}>
      <div style={S.headerRow}>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          style={S.headerButton}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 'bold', overflowWrap: 'anywhere' }}>{name}</span>
            <span style={S.tag(isHttp ? 'blue' : 'green')}>{isHttp ? t('mcp_mode_http') : t('mcp_mode_stdio')}</span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px', flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>
        </button>
        <button
          type="button"
          style={S.deleteBtn}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          aria-label={t('mcp_delete')}
          title={t('mcp_delete')}
        >
          ×
        </button>
      </div>

      {expanded && (
        <div style={S.cardBody as any}>
          <div>
            <label style={S.label}>{t('mcp_mode')}</label>
            <div style={S.row}>
              <button type="button" style={S.modeBtn(mode === 'stdio')} onClick={() => setMode('stdio')}>{t('mcp_mode_stdio')}</button>
              <button type="button" style={S.modeBtn(mode === 'http')} onClick={() => setMode('http')}>{t('mcp_mode_http')}</button>
            </div>
          </div>

          {mode === 'stdio' ? (
            <>
              <div>
                <label style={S.label}>{t('mcp_command')}</label>
                <input style={S.input as any} type="text" value={server.command || ''} placeholder="npx" onInput={(e) => onUpdate({ ...server, command: (e.target as HTMLInputElement).value })} />
              </div>
              <div>
                <label style={S.label}>{t('mcp_args')}</label>
                <input style={S.input as any} type="text" value={argsText} placeholder="@modelcontextprotocol/server-filesystem, /workspace" onInput={(e) => setArgsText((e.target as HTMLInputElement).value)} onBlur={() => onUpdate({ ...server, args: argsText.split(',').map((s: string) => s.trim()).filter(Boolean) })} />
              </div>
              <div>
                <label style={S.label}>{t('mcp_env')}</label>
                <textarea style={S.textarea as any} value={envText} placeholder="NODE_ENV=production" onInput={(e) => setEnvText((e.target as HTMLTextAreaElement).value)} onBlur={() => onUpdate({ ...server, env: linesToDict(envText) })} />
              </div>
            </>
          ) : (
            <>
              <div>
                <label style={S.label}>{t('mcp_url')}</label>
                <input style={S.input as any} type="text" value={server.url || ''} placeholder="http://localhost:3000/mcp" onInput={(e) => onUpdate({ ...server, url: (e.target as HTMLInputElement).value })} />
              </div>
              <div>
                <label style={S.label}>{t('mcp_headers')}</label>
                <textarea style={S.textarea as any} value={headersText} placeholder="Authorization=Bearer sk-xxx" onInput={(e) => setHeadersText((e.target as HTMLTextAreaElement).value)} onBlur={() => onUpdate({ ...server, headers: linesToDict(headersText) })} />
              </div>
            </>
          )}

          <div>
            <label style={S.label}>{t('mcp_timeout')}</label>
            <input style={{ ...(S.input as any), width: '120px' }} type="number" value={server.tool_timeout ?? 30} min={1} max={600} onInput={(e) => onUpdate({ ...server, tool_timeout: Number((e.target as HTMLInputElement).value) || 30 })} />
          </div>
        </div>
      )}
    </div>
  );
}

export function MCPServersEditor({ servers, onChange }: Props) {
  const [newName, setNewName] = useState('');
  const [adding, setAdding] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

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

  const entries = Object.entries(servers || {});

  const handleUpdate = (name: string, server: MCPServer) => {
    onChange({ ...servers, [name]: server });
  };

  const handleDelete = (name: string) => {
    if (!confirm(t('confirm_delete_mcp').replace('{name}', name))) return;
    const next = { ...servers };
    delete next[name];
    onChange(next);
  };

  const handleAdd = () => {
    const trimmed = newName.trim();
    if (!trimmed || servers[trimmed]) return;
    onChange({ ...servers, [trimmed]: { command: '', args: [], env: {}, tool_timeout: 30 } });
    setNewName('');
    setAdding(false);
  };

  return (
    <div id="setting-group-mcp_servers" style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '16px' }}>
      <div style={{ fontSize: '14px', color: 'var(--accent)', marginBottom: '16px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
        <span style={{ color: 'var(--purple)' }}>#</span> {t('mcp_servers_title')}
        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({entries.length})</span>
      </div>


      <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', padding: isMobile ? '12px' : '14px', display: 'flex', flexDirection: isMobile ? 'column' : 'row', justifyContent: 'space-between', alignItems: isMobile ? 'stretch' : 'center', gap: '12px', marginBottom: '12px' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-primary)', marginBottom: '4px' }}>{t('mcp_discovery_title')}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>{t('mcp_discovery_note')}</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <ExternalLinkButton href="https://registry.mcpservers.org/" label={t('mcp_discovery_registry_action')} />
          <ExternalLinkButton href="https://smithery.ai/" label={t('mcp_discovery_smithery_action')} />
        </div>
      </div>

      {entries.length === 0 && !adding && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          {t('mcp_no_servers')}
        </div>
      )}

      {entries.map(([name, server]) => (
        <ServerCard key={name} name={name} server={server} onUpdate={(s) => handleUpdate(name, s)} onDelete={() => handleDelete(name)} />
      ))}

      {adding ? (
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
          <label htmlFor="mcp-server-name" style={srOnly}>{t('mcp_server_name_placeholder')}</label>
          <input
            id="mcp-server-name"
            name="mcp_server_name"
            aria-label={t('mcp_server_name_placeholder')}
            style={S.input as any}
            type="text"
            value={newName}
            placeholder={t('mcp_server_name_placeholder')}
            onInput={(e) => setNewName((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') { setAdding(false); setNewName(''); } }}
            autoFocus
          />
          <button onClick={handleAdd} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', whiteSpace: 'nowrap', width: isMobile ? '100%' : 'auto' }}>{t('mcp_add')}</button>
          <button onClick={() => { setAdding(false); setNewName(''); }} style={{ padding: '8px 12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', width: isMobile ? '100%' : 'auto' }}>{t('btn_cancel')}</button>
        </div>
      ) : (
        <button style={S.addBtn} onClick={() => setAdding(true)}>{t('mcp_add_server')}</button>
      )}
    </div>
  );
}
