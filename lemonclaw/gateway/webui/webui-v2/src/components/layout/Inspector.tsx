import { useEffect, useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { showInspector, selectedInspectorBlock } from '../../stores/ui';
import { ConductorPanel } from '../inspector/ConductorPanel';
import { MemoryPanel } from '../inspector/MemoryPanel';
import { TaskRecoveryPanel } from '../inspector/TaskRecoveryPanel';
import { YesterdayMemo } from '../inspector/YesterdayMemo';

function SelectedBlockView({ block }: { block: NonNullable<typeof selectedInspectorBlock.value> }) {
  if (block.type === 'thinking') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ padding: '4px 8px', background: 'var(--purple-dim)', color: 'var(--purple)', fontFamily: 'var(--font-mono)', fontSize: '15px', borderRadius: '4px', alignSelf: 'flex-start', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
          🧠 THINKING_TRACE
        </div>
        <div style={{ fontSize: '15px', lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'var(--font-mono)' }}>
          {block.data}
        </div>
      </div>
    );
  }

  const tool = block.data;
  const match = typeof tool.detail === 'string' ? tool.detail.match(/^([a-zA-Z0-9_]+)\((.*)\)$/s) : null;
  const toolName = match ? match[1] : 'tool_call';
  const toolArgs = match ? match[2] : tool.detail;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ padding: '4px 8px', background: 'var(--bg-tertiary)', color: 'var(--teal)', fontFamily: 'var(--font-mono)', fontSize: '15px', borderRadius: '4px', border: '1px solid var(--border)' }}>
          🧰 {toolName}
        </div>
        <div style={{ fontSize: '15px', fontFamily: 'var(--font-mono)', color: tool.state === 'running' ? 'var(--accent)' : 'var(--success)' }}>
          STATUS: {tool.state.toUpperCase()}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div style={{ color: 'var(--text-muted)', fontSize: '15px', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>// Arguments</div>
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '15px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowX: 'auto' }}>
          {toolArgs}
        </div>
      </div>

      {tool.result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '15px', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>// Return Value</div>
          <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '15px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowX: 'auto' }}>
            {tool.result}
          </div>
        </div>
      )}
    </div>
  );
}

export function Inspector() {
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 1024);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= 1024);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <>
      {isMobile && showInspector.value && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 940, backdropFilter: 'blur(2px)' }} onClick={() => { showInspector.value = false; selectedInspectorBlock.value = null; }}></div>
      )}
      <aside class={`layout-inspector ${showInspector.value ? '' : 'closed'}`}>
        <div style={{ height: 'var(--topbar-h)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: isMobile ? '0 12px' : '0 16px', flexShrink: 0, minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '15px', color: 'var(--text-muted)' }}>
            // {selectedInspectorBlock.value ? 'TRACE_INSPECTOR' : t('inspector_title')}
          </div>
          {selectedInspectorBlock.value && (
            <button onClick={() => selectedInspectorBlock.value = null} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-secondary)', fontSize: '15px', fontFamily: 'var(--font-mono)', padding: '2px 6px', cursor: 'pointer' }}>
              BACK TO SYSTEM
            </button>
          )}
        </div>
        <div style={{ flex: 1, padding: isMobile ? '12px' : '16px', overflowY: 'auto' }}>
          {selectedInspectorBlock.value ? (
            <SelectedBlockView block={selectedInspectorBlock.value} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <YesterdayMemo />
              <TaskRecoveryPanel />
              <ConductorPanel />
              <MemoryPanel />
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
