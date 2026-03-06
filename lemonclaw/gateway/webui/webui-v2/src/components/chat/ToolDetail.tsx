import { useState } from 'preact/hooks';

export function ToolDetail({ tool }: { tool: any }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = tool.state === 'running';
  
  const match = typeof tool.detail === 'string' ? tool.detail.match(/^([a-zA-Z0-9_]+)\((.*)\)$/s) : null;
  const toolName = match ? match[1] : 'tool_call';
  const toolArgs = match ? match[2] : tool.detail;

  return (
    <div style={{ margin: '6px 0', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden', fontSize: '12px', textAlign: 'left', background: 'var(--bg-secondary)' }}>
      <button 
        onClick={() => setExpanded(!expanded)}
        style={{ 
          width: '100%', background: isRunning ? 'rgba(255, 107, 53, 0.05)' : 'transparent', padding: '6px 10px', 
          fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', 
          display: 'flex', alignItems: 'center', gap: '8px', border: 'none', borderBottom: expanded ? '1px solid var(--border)' : 'none', cursor: 'pointer', textAlign: 'left', transition: 'all 0.2s'
        }}
        onMouseEnter={e => e.currentTarget.style.background = isRunning ? 'rgba(255, 107, 53, 0.1)' : 'var(--bg-tertiary)'}
        onMouseLeave={e => e.currentTarget.style.background = isRunning ? 'rgba(255, 107, 53, 0.05)' : 'transparent'}
      >
        <span style={{ 
          display: 'inline-block', transition: 'transform 0.15s', fontSize: '10px', color: 'var(--text-muted)',
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)'
        }}>
          ▶
        </span>
        <span style={{ color: isRunning ? 'var(--accent)' : 'var(--success)' }}>{isRunning ? '⚙️' : '✅'}</span>
        <span style={{ background: 'var(--bg-primary)', padding: '2px 6px', borderRadius: '4px', border: '1px solid var(--border)', color: 'var(--teal)', fontWeight: 'bold' }}>{toolName}</span>
        {isRunning && <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>executing...</span>}
      </button>

      {expanded && (
        <div>
          <div style={{ padding: '8px 12px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', maxHeight: '150px', overflowY: 'auto', fontSize: '11px', background: 'var(--bg-primary)', boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.2)' }}>
            <div style={{ color: 'var(--purple)', marginBottom: '4px' }}>// Arguments:</div>
            {toolArgs}
          </div>
          
          {tool.result && (
            <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', maxHeight: '200px', overflowY: 'auto', fontSize: '11px', background: 'var(--bg-primary)' }}>
              <div style={{ color: 'var(--teal)', marginBottom: '4px' }}>// Return value:</div>
              {tool.result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}