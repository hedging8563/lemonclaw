import { showInspector, selectedInspectorBlock } from '../../stores/ui';

export function ToolDetail({ tool, id }: { tool: any, id: string }) {
  const isSelected = selectedInspectorBlock.value?.id === id;
  const isRunning = tool.state === 'running';
  
  const match = typeof tool.detail === 'string' ? tool.detail.match(/^([a-zA-Z0-9_]+)\((.*)\)$/s) : null;
  const toolName = match ? match[1] : 'tool_call';

  const stateTone = isRunning 
    ? { bg: isSelected ? 'var(--accent)' : 'rgba(255,107,53,0.15)', color: isSelected ? 'var(--bg-primary)' : 'var(--accent)', border: isSelected ? 'var(--accent)' : 'rgba(255,107,53,0.3)', icon: '⚙️' } 
    : tool.result 
      ? { bg: isSelected ? 'var(--success)' : 'rgba(76,175,80,0.15)', color: isSelected ? 'var(--bg-primary)' : 'var(--success)', border: isSelected ? 'var(--success)' : 'rgba(76,175,80,0.3)', icon: '✅' } 
      : { bg: isSelected ? 'var(--text-secondary)' : 'rgba(148,163,184,0.15)', color: isSelected ? 'var(--bg-primary)' : 'var(--text-secondary)', border: isSelected ? 'var(--text-secondary)' : 'rgba(148,163,184,0.3)', icon: '🧰' };

  const handleClick = () => {
    if (isSelected && showInspector.value) {
      showInspector.value = false;
      selectedInspectorBlock.value = null;
    } else {
      selectedInspectorBlock.value = { type: 'tool', id, data: tool };
      showInspector.value = true;
    }
  };

  return (
    <button 
      onClick={handleClick}
      title="View Tool Trace"
      style={{ 
        display: 'inline-flex', alignItems: 'center', gap: '6px', 
        padding: '4px 10px', margin: '4px 6px 4px 0',
        fontSize: '15px', fontFamily: 'var(--font-mono)', 
        color: stateTone.color, 
        background: stateTone.bg,
        border: '1px solid',
        borderColor: stateTone.border,
        borderRadius: '999px',
        cursor: 'pointer',
        transition: 'all 0.2s',
        boxShadow: isSelected ? `0 2px 8px ${stateTone.border}` : 'none'
      }}
      onMouseEnter={e => {
        if (!isSelected) {
          e.currentTarget.style.filter = 'brightness(1.2)';
        }
      }}
      onMouseLeave={e => {
        if (!isSelected) {
          e.currentTarget.style.filter = 'none';
        }
      }}
    >
      <span class={isRunning ? 'spin-icon' : ''} style={{ display: 'inline-block' }}>{stateTone.icon}</span>
      <span style={{ fontWeight: 500 }}>{toolName}</span>
      {isRunning && (
        <span class="pulse-dot" style={{ background: stateTone.color, marginLeft: '2px' }} />
      )}
    </button>
  );
}
