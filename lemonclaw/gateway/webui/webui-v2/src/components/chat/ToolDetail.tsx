import { useState } from 'preact/hooks';

export function ToolDetail({ tool }: { tool: any }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = tool.state === 'running';

  return (
    <div style={{ margin: '4px 0', border: '1px solid var(--border)', borderRadius: '4px', overflow: 'hidden', fontSize: '12px', textAlign: 'left' }}>
      <button 
        onClick={() => setExpanded(!expanded)}
        style={{ 
          width: '100%', background: 'var(--bg-tertiary)', padding: '6px 10px', 
          fontFamily: 'var(--font-mono)', color: isRunning ? 'var(--accent)' : 'var(--teal)', 
          display: 'flex', alignItems: 'center', gap: '6px', border: 'none', cursor: 'pointer', textAlign: 'left'
        }}
      >
        <span style={{ 
          display: 'inline-block', transition: 'transform 0.15s', fontSize: '10px', color: 'var(--text-muted)',
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)'
        }}>
          ▶
        </span>
        {isRunning ? '⚙️ Executing...' : '✅ Tool Finished'}
      </button>

      {expanded && (
        <div style={{ background: 'var(--bg-secondary)', borderTop: '1px solid var(--border)' }}>
          <div style={{ padding: '6px 10px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', maxHeight: '150px', overflowY: 'auto' }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>// Input:</div>
            {tool.detail}
          </div>
          
          {tool.result && (
            <div style={{ padding: '6px 10px', borderTop: '1px dashed var(--border)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', maxHeight: '200px', overflowY: 'auto' }}>
              <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>// Output:</div>
              {tool.result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}