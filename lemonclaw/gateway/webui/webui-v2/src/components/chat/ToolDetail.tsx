import { showInspector, selectedInspectorBlock } from '../../stores/ui';

export function ToolDetail({ tool, id }: { tool: any, id: string }) {
  const isSelected = selectedInspectorBlock.value?.id === id;
  const isRunning = tool.state === 'running';

  const match = typeof tool.detail === 'string' ? tool.detail.match(/^([a-zA-Z0-9_]+)\((.*)\)$/s) : null;
  const toolName = match ? match[1] : 'tool_call';
  const toolPreview = match ? match[2] : String(tool.detail || tool.result || '').trim();
  const statusLabel = isRunning ? 'Running now' : tool.result ? 'Completed' : 'Queued';

  const stateTone = isRunning
    ? { bg: isSelected ? 'rgba(255,107,53,0.24)' : 'rgba(255,107,53,0.12)', color: 'var(--accent)', border: isSelected ? 'rgba(255,107,53,0.55)' : 'rgba(255,107,53,0.26)', icon: '⚙️' }
    : tool.result
      ? { bg: isSelected ? 'rgba(16,185,129,0.22)' : 'rgba(16,185,129,0.1)', color: 'var(--success)', border: isSelected ? 'rgba(16,185,129,0.5)' : 'rgba(16,185,129,0.24)', icon: '✅' }
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
      class="trace-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'stretch',
        margin: '2px 8px 8px 0',
        color: 'var(--text-primary)',
        background: stateTone.bg,
        borderColor: stateTone.border,
        cursor: 'pointer',
        transition: 'all 0.2s',
        boxShadow: isSelected ? `0 14px 30px ${stateTone.border}` : '0 10px 24px rgba(0,0,0,0.14)'
      }}
      onMouseEnter={e => {
        if (!isSelected) {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.filter = 'brightness(1.04)';
        }
      }}
      onMouseLeave={e => {
        if (!isSelected) {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.filter = 'none';
        }
      }}
    >
      <div class="trace-card__eyebrow" style={{ color: stateTone.color }}>
        <span class={isRunning ? 'spin-icon' : ''} style={{ display: 'inline-block' }}>{stateTone.icon}</span>
        <span>Tool Call</span>
      </div>
      <div class="trace-card__title">{toolName}</div>
      <div class="trace-card__meta" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span>{statusLabel}</span>
        {isRunning ? <span class="pulse-dot" style={{ background: stateTone.color }} /> : null}
      </div>
      <div class="trace-card__snippet">{toolPreview || 'Open the inspector to review arguments and output.'}</div>
      <div class="trace-card__foot">
        <span>{tool.result ? 'Result captured' : isRunning ? 'Awaiting result' : 'Trace available'}</span>
        <span style={{ color: stateTone.color }}>{isSelected ? 'open' : 'inspect'}</span>
      </div>
    </button>
  );
}
