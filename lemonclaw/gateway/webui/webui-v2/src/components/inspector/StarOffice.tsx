import { agents, plans } from '../../stores/conductor';
import { isStreaming } from '../../stores/chat';
import { t } from '../../stores/i18n';
import '../../styles/star-office.css';

function getHueForAgent(id: string) {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash % 360);
}

export function StarOffice() {
  const workerAgents = agents.value || [];
  const isConductorBusy = isStreaming.value || plans.value.length > 0;
  
  let overallStatus = 'idle';
  if (workerAgents.some(a => a.status === 'error')) overallStatus = 'error';
  else if (isConductorBusy) overallStatus = 'executing';
  else if (workerAgents.some(a => a.status === 'busy')) overallStatus = 'executing';

  const slots = [
    { type: 'back-left', bottom: 60, left: 60, zDesk: 2, zCat: 3, faceRight: true },
    { type: 'back-right', bottom: 60, right: 60, zDesk: 2, zCat: 3, faceRight: false },
    { type: 'front-left', bottom: 30, left: 30, zDesk: 10, zCat: 11, faceRight: true },
    { type: 'front-right', bottom: 30, right: 30, zDesk: 10, zCat: 11, faceRight: false },
  ];

  return (
    <div class="star-office">
      <div class={`star-status ${overallStatus.toLowerCase()}`}>{(t as any)(`star_${overallStatus.toLowerCase()}`) || overallStatus}</div>
      
      {overallStatus === 'executing' && (
        <>
          <div class="star-particle" style={{ left: '20%', animationDelay: '0s' }}></div>
          <div class="star-particle" style={{ left: '50%', animationDelay: '0.4s', background: 'var(--accent)' }}></div>
          <div class="star-particle" style={{ left: '80%', animationDelay: '0.7s', background: 'var(--purple)' }}></div>
        </>
      )}

      <div class={`star-scene ${overallStatus}`}>
        <div class={`star-dash ${isConductorBusy ? 'executing' : ''}`}>
          {Array.from({ length: 5 }).map((_, i) => (
             <div key={i} class="star-dash-bar" style={{ height: `${10 + (i * 4)}px`, animationDelay: `${i * 0.1}s`, opacity: isConductorBusy ? 1 : 0.3 }}></div>
          ))}
        </div>
        
        <div class={`star-rack left ${overallStatus === 'executing' ? 'executing' : ''}`}><div class="star-rack-light" style={{top:'10px'}}></div><div class="star-rack-light" style={{top:'30px'}}></div></div>
        <div class={`star-rack right ${overallStatus === 'executing' ? 'executing' : ''}`}><div class="star-rack-light" style={{top:'10px'}}></div><div class="star-rack-light" style={{top:'30px'}}></div></div>

        <div class="star-office-floor"></div>

        {/* Dynamic Worker Agents */}
        {workerAgents.slice(0, 4).map((agent, idx) => {
          const slot = slots[idx];
          const hue = getHueForAgent(agent.id);
          const isBusy = agent.status === 'busy';
          const isError = agent.status === 'error';
          
          return (
            <div key={agent.id}>
              <div 
                class="star-desk-side" 
                style={{ 
                  ...(slot.faceRight ? { left: `${slot.left}px` } : { right: `${slot.right}px` }),
                  bottom: `${slot.bottom}px`,
                  zIndex: slot.zDesk
                }}
              >
                <div class="star-monitor-side" style={{ 
                  ...(slot.faceRight ? { right: '4px' } : { left: '4px' }),
                  boxShadow: isError ? 'inset 0 0 6px #F00' : (isBusy ? `inset 0 0 6px hsl(${hue}, 100%, 50%)` : 'none'),
                  borderColor: isBusy ? `hsl(${hue}, 50%, 50%)` : 'var(--border)'
                }}></div>
              </div>
              
              <div 
                class="star-cat" 
                style={{ 
                  bottom: `${slot.bottom + 20}px`, 
                  ...(slot.faceRight ? { left: `${slot.left + 10}px` } : { right: `${slot.right + 10}px` }),
                  filter: `hue-rotate(${hue}deg)`,
                  transform: slot.faceRight ? 'none' : 'scaleX(-1)',
                  zIndex: slot.zCat
                }}
              >
                <div 
                  class="star-cat-body" 
                  style={{
                    animation: isError ? 'cat-shake 0.2s infinite' : (isBusy ? 'cat-type 0.3s infinite alternate' : 'none')
                  }}
                >
                  {/* Floating Name Tag */}
                  <div style={{ position: 'absolute', top: '-18px', left: '-10px', fontSize: '8px', color: 'var(--text-primary)', background: 'var(--bg-secondary)', border: '1px solid var(--border)', padding: '0 4px', borderRadius: '2px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', transform: slot.faceRight ? 'none' : 'scaleX(-1)' }}>
                    {agent.id.substring(0,8)}
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {/* Center Conductor */}
        <div class="star-desk-main">
          <div class={`star-monitor-main ${isConductorBusy ? 'executing' : ''}`}></div>
        </div>
        <div class="star-cat agent-center">
          <div 
            class="star-cat-body" 
            style={{ 
              animation: isConductorBusy ? 'cat-type 0.2s infinite' : 'none' 
            }}
          >
             <div style={{ position: 'absolute', top: '-18px', left: '-16px', fontSize: '8px', color: 'var(--accent)', background: 'rgba(255, 107, 53, 0.1)', border: '1px solid var(--accent)', padding: '0 4px', borderRadius: '2px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
               ORCHESTRATOR
             </div>
          </div>
        </div>

      </div>
    </div>
  );
}