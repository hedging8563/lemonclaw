import { useState } from 'preact/hooks';

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

const S = {
  card: { marginBottom: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' } as const,
  cardHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', cursor: 'pointer', gap: '8px' } as const,
  cardBody: { padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: '10px' } as const,
  label: { display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' } as const,
  input: { width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box' } as const,
  textarea: { width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', resize: 'vertical', minHeight: '60px', boxSizing: 'border-box' } as const,
  tag: (color: string) => ({ fontSize: '10px', padding: '2px 6px', borderRadius: '3px', fontFamily: 'var(--font-mono)', background: color === 'green' ? 'rgba(76,175,80,0.15)' : 'rgba(100,149,237,0.15)', color: color === 'green' ? 'var(--success)' : 'cornflowerblue', border: `1px solid ${color === 'green' ? 'rgba(76,175,80,0.3)' : 'rgba(100,149,237,0.3)'}` }),
  deleteBtn: { background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '16px', padding: '4px 8px', borderRadius: '4px', lineHeight: 1 } as const,
  addBtn: { width: '100%', padding: '10px', background: 'var(--bg-secondary)', border: '1px dashed var(--border)', borderRadius: '6px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px' } as const,
  row: { display: 'flex', gap: '10px' } as const,
  modeBtn: (active: boolean) => ({ flex: 1, padding: '6px', background: active ? 'var(--bg-tertiary)' : 'transparent', border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`, borderRadius: '4px', color: active ? 'var(--accent)' : 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px' }),
};

function dictToLines(d: Record<string, string> | undefined): string {
  if (!d) return '';
  return Object.entries(d).map(([k, v]) => `${k}=${v}`).join('\n');
}

function linesToDict(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const idx = trimmed.indexOf('=');
    if (idx > 0) {
      result[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
  }
  return result;
}

function ServerCard({ name, server, onUpdate, onDelete }: {
  name: string;
  server: MCPServer;
  onUpdate: (s: MCPServer) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isHttp = !!server.url;
  const mode = isHttp ? 'http' : 'stdio';

  const setMode = (m: 'stdio' | 'http') => {
    if (m === 'http') {
      onUpdate({ url: server.url || '', headers: server.headers || {}, tool_timeout: server.tool_timeout ?? 30 });
    } else {
      onUpdate({ command: server.command || '', args: server.args || [], env: server.env || {}, tool_timeout: server.tool_timeout ?? 30 });
    }
  };

  const summary = isHttp ? (server.url || 'no url') : (server.command ? `${server.command} ${(server.args || []).join(' ')}` : 'no command');

  return (
    <div style={S.card}>
      <div style={S.cardHeader} onClick={() => setExpanded(!expanded)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 'bold' }}>{name}</span>
          <span style={S.tag(isHttp ? 'blue' : 'green')}>{isHttp ? 'HTTP' : 'STDIO'}</span>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <button style={S.deleteBtn} onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete">×</button>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div style={S.cardBody as any}>
          {/* Mode selector */}
          <div>
            <label style={S.label}>mode</label>
            <div style={S.row}>
              <button style={S.modeBtn(mode === 'stdio')} onClick={() => setMode('stdio')}>Stdio</button>
              <button style={S.modeBtn(mode === 'http')} onClick={() => setMode('http')}>HTTP</button>
            </div>
          </div>

          {mode === 'stdio' ? (
            <>
              <div>
                <label style={S.label}>command</label>
                <input style={S.input as any} type="text" value={server.command || ''} placeholder="npx" onInput={(e) => onUpdate({ ...server, command: (e.target as any).value })} />
              </div>
              <div>
                <label style={S.label}>args (comma-separated)</label>
                <input style={S.input as any} type="text" value={(server.args || []).join(', ')} placeholder="@modelcontextprotocol/server-filesystem, /tmp" onInput={(e) => onUpdate({ ...server, args: (e.target as any).value.split(',').map((s: string) => s.trim()).filter(Boolean) })} />
              </div>
              <div>
                <label style={S.label}>env (KEY=VALUE, one per line)</label>
                <textarea style={S.textarea as any} value={dictToLines(server.env)} placeholder="NODE_ENV=production" onInput={(e) => onUpdate({ ...server, env: linesToDict((e.target as any).value) })} />
              </div>
            </>
          ) : (
            <>
              <div>
                <label style={S.label}>url</label>
                <input style={S.input as any} type="text" value={server.url || ''} placeholder="http://localhost:3000/mcp" onInput={(e) => onUpdate({ ...server, url: (e.target as any).value })} />
              </div>
              <div>
                <label style={S.label}>headers (KEY=VALUE, one per line)</label>
                <textarea style={S.textarea as any} value={dictToLines(server.headers)} placeholder="Authorization=Bearer sk-xxx" onInput={(e) => onUpdate({ ...server, headers: linesToDict((e.target as any).value) })} />
              </div>
            </>
          )}

          <div>
            <label style={S.label}>tool_timeout (seconds)</label>
            <input style={{ ...(S.input as any), width: '120px' }} type="number" value={server.tool_timeout ?? 30} min={1} max={600} onInput={(e) => onUpdate({ ...server, tool_timeout: Number((e.target as any).value) || 30 })} />
          </div>
        </div>
      )}
    </div>
  );
}

export function MCPServersEditor({ servers, onChange }: Props) {
  const [newName, setNewName] = useState('');
  const [adding, setAdding] = useState(false);

  const entries = Object.entries(servers || {});

  const handleUpdate = (name: string, server: MCPServer) => {
    onChange({ ...servers, [name]: server });
  };

  const handleDelete = (name: string) => {
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
    <div style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '16px' }}>
      <div style={{ fontSize: '14px', color: 'var(--accent)', marginBottom: '16px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
        <span style={{ color: 'var(--purple)' }}>#</span> mcp_servers
        <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({entries.length})</span>
      </div>

      {entries.length === 0 && !adding && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '4px', textAlign: 'center' }}>
          No MCP servers configured. Add one to extend your agent with external tools.
        </div>
      )}

      {entries.map(([name, server]) => (
        <ServerCard
          key={name}
          name={name}
          server={server}
          onUpdate={(s) => handleUpdate(name, s)}
          onDelete={() => handleDelete(name)}
        />
      ))}

      {adding ? (
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
          <input
            style={S.input as any}
            type="text"
            value={newName}
            placeholder="server name (e.g. filesystem)"
            onInput={(e) => setNewName((e.target as any).value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); if (e.key === 'Escape') { setAdding(false); setNewName(''); } }}
            autoFocus
          />
          <button onClick={handleAdd} style={{ padding: '8px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', whiteSpace: 'nowrap' }}>Add</button>
          <button onClick={() => { setAdding(false); setNewName(''); }} style={{ padding: '8px 12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>Cancel</button>
        </div>
      ) : (
        <button style={S.addBtn} onClick={() => setAdding(true)}>+ Add MCP Server</button>
      )}
    </div>
  );
}
