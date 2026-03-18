import { useEffect, useRef, useState } from 'preact/hooks';
import { agents, plans, loadConductor } from '../../stores/conductor';
import { t } from '../../stores/i18n';

const shellStyle = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '12px',
} as const;

function pillStyle(active = false) {
  return {
    padding: '4px 8px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(10, 186, 181, 0.1)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    cursor: 'pointer',
  } as const;
}

export function ConductorPanel() {
  const timerRef = useRef<any>(null);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    void loadConductor();

    const startPolling = () => {
      if (timerRef.current) clearInterval(timerRef.current);
      const hasBusy = agents.peek().some((agent) => agent.status === 'busy');
      timerRef.current = setInterval(() => {
        if (document.visibilityState === 'visible') {
          void loadConductor().then(() => {
            const nowBusy = agents.peek().some((agent) => agent.status === 'busy');
            if (nowBusy !== hasBusy) startPolling();
          });
        }
      }, hasBusy ? 3000 : 15000);
    };

    startPolling();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const conductorBusy = agents.value.some((agent) => agent.status === 'busy');
  const busyAgents = agents.value.filter((agent) => agent.status === 'busy').length;
  const errorAgents = agents.value.filter((agent) => agent.status === 'error').length;
  const summaryMessage = plans.value[0]?.message || t('no_plans');

  return (
    <div style={shellStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '1.5px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>// {t('conductor_title')}</span>
            {conductorBusy ? <span style={{ width: '6px', height: '6px', background: 'var(--accent)', borderRadius: '50%', animation: 'server-blink 1s infinite' }}></span> : null}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
            <span style={pillStyle(Boolean(plans.value.length))}>{`plans: ${plans.value.length}`}</span>
            <span style={pillStyle(Boolean(busyAgents))}>{`busy: ${busyAgents}`}</span>
            <span style={pillStyle(Boolean(errorAgents))}>{`errors: ${errorAgents}`}</span>
            <span style={pillStyle()}>{`agents: ${agents.value.length}`}</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{summaryMessage}</div>
        </div>
        <button onClick={() => setExpanded((value) => !value)} style={pillStyle(expanded)}>
          {expanded ? t('memo_collapse') : t('memo_expand')}
        </button>
      </div>

      {expanded ? (
        <div style={{ display: 'grid', gap: '12px' }}>
          <div style={{ display: 'grid', gap: '8px', maxHeight: '320px', overflowY: 'auto', paddingRight: '4px' }}>
            {plans.value.length === 0 ? (
              <div style={{ padding: '12px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('no_plans')}</div>
              </div>
            ) : (
              plans.value.map((plan) => (
                <div key={plan.request_id} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', position: 'relative', overflow: 'hidden' }}>
                  <div style={{ position: 'absolute', inset: 0, width: `${Math.min(100, Math.round((plan.progress || 0) * 100))}%`, background: 'rgba(10, 186, 181, 0.08)', pointerEvents: 'none', transition: 'width 0.3s ease-out' }} />
                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ ...pillStyle(plan.phase === 'COMPLETED'), cursor: 'default' }}>{plan.phase || 'UNKNOWN'}</span>
                      {plan.complexity ? <span style={{ ...pillStyle(), cursor: 'default' }}>{`lvl:${plan.complexity}`}</span> : null}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.5, marginBottom: plan.subtasks?.length ? '10px' : '0' }}>{plan.message}</div>
                    {plan.subtasks?.length ? (
                      <details>
                        <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{`subtasks · ${plan.subtasks.length}`}</summary>
                        <div style={{ display: 'grid', gap: '6px', marginTop: '8px' }}>
                          {plan.subtasks.map((subtask: any) => (
                            <div key={subtask.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                              <span style={{ color: subtask.status === 'completed' ? 'var(--success)' : subtask.status === 'executing' ? 'var(--accent)' : 'var(--text-muted)', marginTop: '2px', fontSize: '10px' }}>
                                {subtask.status === 'completed' ? '✓' : subtask.status === 'executing' ? '⚙' : '○'}
                              </span>
                              <div style={{ flex: 1, color: subtask.status === 'completed' ? 'var(--text-muted)' : 'var(--text-secondary)', lineHeight: 1.4 }}>
                                {subtask.assigned_agent ? <span style={{ color: 'var(--teal)', marginRight: '4px' }}>[{subtask.assigned_agent}]</span> : null}
                                {subtask.description}
                              </div>
                            </div>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>

          <details open={agents.value.length <= 6} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
              agent pool · {agents.value.length}
            </summary>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px', maxHeight: '180px', overflowY: 'auto', paddingRight: '4px' }}>
              {agents.value.map((agent) => {
                const isBusy = agent.status === 'busy';
                const isError = agent.status === 'error';
                return (
                  <div
                    key={agent.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      background: isError ? 'rgba(255, 68, 68, 0.1)' : isBusy ? 'rgba(10, 186, 181, 0.1)' : 'var(--bg-secondary)',
                      border: '1px solid',
                      borderColor: isError ? 'rgba(255, 68, 68, 0.3)' : isBusy ? 'rgba(10, 186, 181, 0.3)' : 'var(--border)',
                      padding: '4px 10px',
                      borderRadius: '20px',
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    <span style={{ color: isError ? 'var(--error)' : isBusy ? 'var(--teal)' : 'var(--text-muted)', fontSize: '8px' }}>
                      {isError ? '✖' : isBusy ? '●' : '○'}
                    </span>
                    <span style={{ color: isError ? 'var(--error)' : isBusy ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{agent.id}</span>
                  </div>
                );
              })}
            </div>
          </details>
        </div>
      ) : null}
    </div>
  );
}
