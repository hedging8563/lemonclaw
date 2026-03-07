import { useEffect, useRef } from 'preact/hooks';
import { agents, plans, loadConductor } from '../../stores/conductor';
import { t } from '../../stores/i18n';

export function ConductorPanel() {
  const timerRef = useRef<any>(null);

  useEffect(() => {
    loadConductor();

    const startPolling = () => {
      if (timerRef.current) clearInterval(timerRef.current);
      const hasBusy = agents.peek().some(a => a.status === 'busy');
      timerRef.current = setInterval(() => {
        if (document.visibilityState === 'visible') {
          loadConductor().then(() => {
            // Adjust interval if busy state changed
            const nowBusy = agents.peek().some(a => a.status === 'busy');
            if (nowBusy !== hasBusy) startPolling();
          });
        }
      }, hasBusy ? 3000 : 15000);
    };

    startPolling();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>// CONDUCTOR</span>
        {agents.value.some(a => a.status === 'busy') && <span style={{ width: '6px', height: '6px', background: 'var(--accent)', borderRadius: '50%', animation: 'server-blink 1s infinite' }}></span>}
      </div>
      
      {agents.value.length === 0 && plans.value.length === 0 ? (
        <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_plans')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Plans/Tasks with Progress */}
          {plans.value.map(p => (
            <div key={p.request_id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: `${(p.progress || 0) * 100}%`, background: 'var(--bg-tertiary)', zIndex: 0, transition: 'width 0.3s ease-out' }}></div>
              
              <div style={{ position: 'relative', zIndex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                  <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: p.phase === 'COMPLETED' ? 'var(--success)' : 'var(--accent)', background: p.phase === 'COMPLETED' ? 'rgba(76, 175, 80, 0.1)' : 'rgba(255, 107, 53, 0.1)', padding: '2px 6px', borderRadius: '4px', border: '1px solid', borderColor: p.phase === 'COMPLETED' ? 'rgba(76, 175, 80, 0.3)' : 'rgba(255, 107, 53, 0.3)' }}>
                    {p.phase || 'UNKNOWN'}
                  </div>
                  {p.complexity && (
                    <div style={{ fontSize: '9px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                      Lvl: {p.complexity}
                    </div>
                  )}
                </div>
                
                <div style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: p.subtasks?.length ? '12px' : '0', lineHeight: '1.4' }}>
                  {p.message}
                </div>

                {/* Subtasks Tree */}
                {p.subtasks && p.subtasks.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', borderTop: '1px dashed var(--border)', paddingTop: '10px' }}>
                    {p.subtasks.map((st: any) => (
                      <div key={st.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                        <span style={{ color: st.status === 'completed' ? 'var(--success)' : (st.status === 'executing' ? 'var(--accent)' : 'var(--text-muted)'), marginTop: '2px', fontSize: '10px' }}>
                          {st.status === 'completed' ? '✓' : (st.status === 'executing' ? '⚙' : '○')}
                        </span>
                        <div style={{ flex: 1, color: st.status === 'completed' ? 'var(--text-muted)' : 'var(--text-secondary)', lineHeight: '1.4' }}>
                          {st.assigned_agent && <span style={{ color: 'var(--teal)', marginRight: '4px' }}>[{st.assigned_agent}]</span>}
                          {st.description}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Agents Pool Chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {agents.value.map(a => {
              const isBusy = (a.status || 'idle') === 'busy';
              const isErr = a.status === 'error';
              return (
                <div key={a.id} style={{ 
                  display: 'flex', alignItems: 'center', gap: '6px', 
                  background: isErr ? 'rgba(255, 68, 68, 0.1)' : (isBusy ? 'rgba(10, 186, 181, 0.1)' : 'var(--bg-secondary)'), 
                  border: '1px solid', 
                  borderColor: isErr ? 'rgba(255, 68, 68, 0.3)' : (isBusy ? 'rgba(10, 186, 181, 0.3)' : 'var(--border)'), 
                  padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontFamily: 'var(--font-mono)',
                  transition: 'all 0.3s'
                }}>
                  <span style={{ color: isErr ? 'var(--error)' : (isBusy ? 'var(--teal)' : 'var(--text-muted)'), fontSize: '8px' }}>
                    {isErr ? '✖' : (isBusy ? '●' : '○')}
                  </span>
                  <span style={{ color: isErr ? 'var(--error)' : (isBusy ? 'var(--text-primary)' : 'var(--text-secondary)') }}>{a.id}</span>
                </div>
              )
            })}
          </div>

        </div>
      )}
    </div>
  );
}