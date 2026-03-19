import { showInspector, selectedInspectorBlock } from '../../stores/ui';

export function ThinkingBlock({ content, id }: { content: string, id: string }) {
  const isSelected = selectedInspectorBlock.value?.id === id;

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
      style={{ 
        display: 'inline-flex', alignItems: 'center', gap: '6px', 
        padding: '4px 10px', margin: '4px 6px 4px 0',
        fontSize: '15px', fontFamily: 'var(--font-mono)', 
        color: isSelected ? 'var(--bg-primary)' : 'var(--purple)', 
        background: isSelected ? 'var(--purple)' : 'var(--purple-dim)',
        border: '1px solid',
        borderColor: isSelected ? 'var(--purple)' : 'rgba(168, 85, 247, 0.3)',
        borderRadius: '999px',
        cursor: 'pointer',
        transition: 'all 0.2s',
        boxShadow: isSelected ? '0 2px 8px rgba(168, 85, 247, 0.4)' : 'none'
      }}
      onMouseEnter={e => {
        if (!isSelected) {
          e.currentTarget.style.background = 'rgba(168, 85, 247, 0.25)';
        }
      }}
      onMouseLeave={e => {
        if (!isSelected) {
          e.currentTarget.style.background = 'var(--purple-dim)';
        }
      }}
    >
      <span>🧠</span>
      <span style={{ fontWeight: 500 }}>Thinking...</span>
    </button>
  );
}
