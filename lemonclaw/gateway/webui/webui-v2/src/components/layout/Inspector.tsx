import { useEffect, useState } from 'preact/hooks';
import { showInspector } from '../../stores/ui';
import { ConductorPanel } from '../inspector/ConductorPanel';
import { MemoryPanel } from '../inspector/MemoryPanel';
import { StarOffice } from '../inspector/StarOffice';
import { TaskRecoveryPanel } from '../inspector/TaskRecoveryPanel';
import { YesterdayMemo } from '../inspector/YesterdayMemo';

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
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 940, backdropFilter: 'blur(2px)' }} onClick={() => { showInspector.value = false; }}></div>
      )}
      <aside class={`layout-inspector ${showInspector.value ? '' : 'closed'}`}>
        <div style={{ height: 'var(--topbar-h)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: isMobile ? '0 12px' : '0 16px', flexShrink: 0, minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
            // INSPECTOR
          </div>
        </div>
        <div style={{ flex: 1, padding: isMobile ? '12px' : '16px', overflowY: 'auto' }}>
          <YesterdayMemo />
          <StarOffice />
          <ConductorPanel />
          <TaskRecoveryPanel />
          <MemoryPanel />
        </div>
      </aside>
    </>
  );
}
