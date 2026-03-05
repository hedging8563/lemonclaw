import { useState } from 'preact/hooks';

export function ThinkingBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{ margin: '4px 0 8px', borderLeft: '2px solid var(--purple)', borderRadius: '2px', overflow: 'hidden', background: 'linear-gradient(90deg, var(--purple-dim) 0%, transparent 100%)' }}>
      <button 
        onClick={() => setExpanded(!expanded)}
        style={{ 
          display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 8px', 
          fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--purple)', 
          cursor: 'pointer', background: 'none', border: 'none', width: '100%', textAlign: 'left'
        }}
      >
        <span style={{ 
          display: 'inline-block', transition: 'transform 0.15s', fontSize: '10px',
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)'
        }}>
          ▶
        </span>
        THINKING {expanded ? '' : '...'}
      </button>
      
      {expanded && (
        <div style={{ padding: '6px 10px', fontSize: '12px', lineHeight: 1.6, color: 'var(--text-muted)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', textAlign: 'left', borderTop: '1px solid rgba(168, 85, 247, 0.1)' }}>
          {content}
        </div>
      )}
    </div>
  );
}