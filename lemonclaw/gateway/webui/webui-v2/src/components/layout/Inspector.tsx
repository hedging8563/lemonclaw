import { StarOffice } from '../inspector/StarOffice';
import { ConductorPanel } from '../inspector/ConductorPanel';
import { MemoryPanel } from '../inspector/MemoryPanel';
import { YesterdayMemo } from '../inspector/YesterdayMemo';
import { showInspector } from '../../stores/ui';

import { useEffect, useState } from 'preact/hooks';

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
      <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 940, backdropFilter: 'blur(2px)' }} onClick={() => showInspector.value = false}></div>
    )}
    <aside class={`layout-inspector ${showInspector.value ? '' : 'closed'}`}>
      <div style={{ height: 'var(--topbar-h)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: '0 16px', flexShrink: 0, minWidth: '320px' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
          // INSPECTOR
        </div>
      </div>
      <div style={{ flex: 1, padding: '16px', overflowY: 'auto' }}>
        <YesterdayMemo />
        <StarOffice />
        <ConductorPanel />
        <MemoryPanel />
      </div>
    </aside>
    </>
  );
}