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
        <div style={{ padding: '5px 10px', background: 'rgba(124, 58, 237, 0.12)', color: 'var(--purple)', fontFamily: 'var(--font-display)', fontSize: '11px', borderRadius: '999px', alignSelf: 'flex-start', border: '1px solid rgba(168, 85, 247, 0.28)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          🧠 Thinking Trace
        </div>
        <div style={{ fontSize: '14px', lineHeight: 1.72, color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'var(--font-reading)' }}>
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
        <div style={{ padding: '5px 10px', background: 'rgba(16, 185, 129, 0.08)', color: 'var(--teal)', fontFamily: 'var(--font-display)', fontSize: '11px', borderRadius: '999px', border: '1px solid rgba(16, 185, 129, 0.2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          🧰 {toolName}
        </div>
        <div style={{ fontSize: '12px', fontFamily: 'var(--font-display)', color: tool.state === 'running' ? 'var(--accent)' : 'var(--success)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Status: {tool.state}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div style={{ color: 'var(--text-muted)', fontSize: '11px', fontFamily: 'var(--font-display)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Arguments</div>
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowX: 'auto', lineHeight: 1.6 }}>
          {toolArgs}
        </div>
      </div>

      {tool.result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', fontFamily: 'var(--font-display)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Return Value</div>
          <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowX: 'auto', lineHeight: 1.6 }}>
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
          <div style={{ fontFamily: 'var(--font-display)', fontSize: '12px', color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            // {selectedInspectorBlock.value ? 'TRACE_INSPECTOR' : t('inspector_title')}
          </div>
          {selectedInspectorBlock.value && (
            <button onClick={() => selectedInspectorBlock.value = null} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '999px', color: 'var(--text-secondary)', fontSize: '11px', fontFamily: 'var(--font-display)', padding: '5px 9px', cursor: 'pointer', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
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
