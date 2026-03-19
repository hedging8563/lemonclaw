import { showInspector, selectedInspectorBlock } from '../../stores/ui';

export function ThinkingBlock({ content, id }: { content: string, id: string }) {
  const isSelected = selectedInspectorBlock.value?.id === id;
  const snippet = content.replace(/\s+/g, ' ').trim();

  const handleClick = () => {
    if (isSelected && showInspector.value) {
      showInspector.value = false;
      selectedInspectorBlock.value = null;
    } else {
      selectedInspectorBlock.value = { type: 'thinking', id, data: content };
      showInspector.value = true;
    }
  };

  return (
    <button
      onClick={handleClick}
      title="View Thinking Process"
      class="trace-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'stretch',
        margin: '2px 8px 8px 0',
        color: 'var(--text-primary)',
        background: isSelected
          ? 'linear-gradient(180deg, rgba(124, 58, 237, 0.28) 0%, rgba(124, 58, 237, 0.14) 100%)'
          : 'linear-gradient(180deg, rgba(124, 58, 237, 0.14) 0%, rgba(124, 58, 237, 0.06) 100%)',
        borderColor: isSelected ? 'rgba(124, 58, 237, 0.58)' : 'rgba(124, 58, 237, 0.26)',
        cursor: 'pointer',
        transition: 'all 0.2s',
        boxShadow: isSelected ? '0 14px 30px rgba(124, 58, 237, 0.22)' : '0 10px 24px rgba(0,0,0,0.14)',
      }}
      onMouseEnter={e => {
        if (!isSelected) {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.borderColor = 'rgba(124, 58, 237, 0.42)';
        }
      }}
      onMouseLeave={e => {
        if (!isSelected) {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.borderColor = 'rgba(124, 58, 237, 0.26)';
        }
      }}
    >
      <div class="trace-card__eyebrow" style={{ color: isSelected ? 'var(--text-primary)' : 'var(--purple)' }}>
        <span>🧠</span>
        <span>Reasoning</span>
      </div>
      <div class="trace-card__title">Thinking Trace</div>
      <div class="trace-card__meta">Inline summary, full trace in inspector</div>
      <div class="trace-card__snippet">{snippet || 'Model reasoning is being assembled.'}</div>
      <div class="trace-card__foot">
        <span>{isSelected ? 'Inspector open' : 'Open inspector'}</span>
        <span style={{ color: isSelected ? 'var(--text-primary)' : 'var(--purple)' }}>view</span>
      </div>
    </button>
  );
}
