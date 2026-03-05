import { useEffect } from 'preact/hooks';
import { agents, plans, loadConductor } from '../../stores/conductor';
import { t } from '../../stores/i18n';

export function ConductorPanel() {
  useEffect(() => {
    loadConductor();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadConductor();
    }, 3000); 
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px' }}>
        // CONDUCTOR
      </div>
      
      {agents.value.length === 0 && plans.value.length === 0 ? (
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_plans')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {agents.value.map(a => (
            <div key={a.id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{a.id}</span>
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: (a.status || 'idle') === 'idle' ? 'var(--text-muted)' : 'var(--teal)' }}>
                  {(a.status || 'idle') === 'idle' ? '○ IDLE' : '● ' + (a.status || '').toUpperCase()}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{a.model}</div>
            </div>
          ))}
          {plans.value.map(p => (
            <div key={p.request_id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--accent)', marginBottom: '4px' }}>Plan: {p.phase || 'UNKNOWN'}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{p.message}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}