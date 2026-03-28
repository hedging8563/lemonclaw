import { agents, plans, templates } from '../../stores/conductor';
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

function shortId(id: string | null | undefined) {
  if (!id) return 'unassigned';
  return id.length > 12 ? `${id.slice(0, 10)}...` : id;
}

function statusTone(status: string) {
  if (status === 'completed') return 'success';
  if (status === 'running' || status === 'busy') return 'accent';
  if (status === 'failed' || status === 'error' || status === 'blocked') return 'error';
  return 'muted';
}

export function StarOffice() {
  const workerAgents = agents.value || [];
  const isConductorBusy = isStreaming.value || plans.value.length > 0;
  const activePlan = plans.value[0];
  const activeTemplate = activePlan?.swarm_template_label || '';
  const activeTemplateData = templates.value.find((template) => template.id === activePlan?.swarm_template_id) || null;
  const subtasks = activePlan?.subtasks || [];
  const completedSubtaskIds = new Set(subtasks.filter((task) => task.status === 'completed').map((task) => task.id));
  const runningSubtasks = subtasks.filter((task) => task.status === 'running');
  const blockedSubtasks = subtasks.filter(
    (task) => {
      const deps = task.depends_on || [];
      return task.status === 'pending' && deps.length > 0 && deps.some((dep) => !completedSubtaskIds.has(dep));
    },
  );
  const readySubtasks = subtasks.filter(
    (task) => {
      const deps = task.depends_on || [];
      return task.status === 'pending' && deps.every((dep) => completedSubtaskIds.has(dep));
    },
  );
  const handoffSubtasks = subtasks.filter((task) => (task.depends_on || []).length > 0);
  const completedCount = subtasks.filter((task) => task.status === 'completed').length;
  const busyAgents = workerAgents.filter((agent) => agent.status === 'busy').length;
  const errorAgents = workerAgents.filter((agent) => agent.status === 'error').length;
  const laneTemplates = (activeTemplateData?.roles?.length ? activeTemplateData.roles : [])
    .map((role) => ({
      id: role.id,
      label: role.label,
      tasks: subtasks.filter((task) => task.role_hint === role.id || (role.id === 'lead' && task.role_hint == null)),
      agent: workerAgents.find((agent) => agent.role === role.id) || null,
    }))
    .filter((lane) => lane.tasks.length > 0 || lane.agent);
  const derivedRoleLanes = laneTemplates.length
    ? laneTemplates
    : Array.from(
        new Map(
          subtasks
            .map((task) => task.role_hint || 'unassigned')
            .filter(Boolean)
            .map((roleId) => [roleId, roleId]),
        ).values(),
      ).map((roleId) => ({
        id: roleId,
        label: roleId === 'unassigned' ? 'Unassigned' : roleId.replace(/_/g, ' '),
        tasks: subtasks.filter((task) => (task.role_hint || 'unassigned') === roleId),
        agent: workerAgents.find((agent) => agent.role === roleId) || null,
      }));
  const roleLanes = derivedRoleLanes.slice(0, 4);

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
      {activeTemplate ? (
        <div style={{
          position: 'absolute',
          top: '36px',
          left: '50%',
          transform: 'translateX(-50%)',
          fontSize: '10px',
          fontFamily: 'var(--font-ui)',
          color: 'var(--text-secondary)',
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          borderRadius: '999px',
          padding: '3px 8px',
          zIndex: 20,
          whiteSpace: 'nowrap',
        }}>
          {`TEAM · ${activeTemplate}`}
        </div>
      ) : null}

      <div class="star-hud star-hud-top-left">
        <div class="star-hud-kicker">current team</div>
        <div class="star-hud-title">{activeTemplate || 'Single-instance swarm'}</div>
        <div class="star-hud-body">
          {activePlan?.swarm_goal ? activePlan.swarm_goal : activePlan?.message || 'Idle and ready for the next swarm task.'}
        </div>
        <div class="star-hud-pills">
          <span class="star-hud-pill accent">{`tasks ${subtasks.length}`}</span>
          <span class="star-hud-pill muted">{`ready ${readySubtasks.length}`}</span>
          <span class="star-hud-pill error">{`blocked ${blockedSubtasks.length}`}</span>
        </div>
      </div>

      <div class="star-hud star-hud-top-right">
        <div class="star-hud-kicker">status</div>
        <div class="star-hud-metric-row">
          <span class="star-hud-metric">
            <strong>{busyAgents}</strong>
            <span>busy agents</span>
          </span>
          <span class="star-hud-metric">
            <strong>{runningSubtasks.length}</strong>
            <span>running lanes</span>
          </span>
          <span class="star-hud-metric">
            <strong>{errorAgents}</strong>
            <span>errors</span>
          </span>
        </div>
        <div class="star-hud-body">
          {completedCount
            ? `${completedCount} completed, ${handoffSubtasks.length} with handoff deps`
            : 'No completed lanes yet.'}
        </div>
      </div>

      <div class="star-hud star-hud-bottom-left">
        <div class="star-hud-kicker">role roster</div>
        <div class="star-hud-lanes">
          {roleLanes.length ? roleLanes.map((lane) => {
            const laneActiveTask = lane.tasks.find((task) => task.status !== 'completed') || lane.tasks[0];
            const laneTone = laneActiveTask ? statusTone(laneActiveTask.status) : (lane.agent ? statusTone(lane.agent.status) : 'muted');
            return (
              <div class={`star-hud-lane ${laneTone}`}>
                <div class="star-hud-lane-head">
                  <span>{lane.label}</span>
                  <span class={`star-hud-pill ${laneTone}`}>{lane.agent ? shortId(lane.agent.id) : 'standby'}</span>
                </div>
                <div class="star-hud-lane-task">
                  {laneActiveTask ? laneActiveTask.description : 'Awaiting assignment'}
                </div>
              </div>
            );
          }) : (
            <div class="star-hud-empty">No lanes assigned yet.</div>
          )}
        </div>
      </div>

      <div class="star-hud star-hud-bottom-right">
        <div class="star-hud-kicker">handoff</div>
        <div class="star-hud-lanes">
          {handoffSubtasks.length ? handoffSubtasks.slice(0, 4).map((task) => {
            const deps = (task.depends_on || []).map((depId) => subtasks.find((item) => item.id === depId)).filter(Boolean);
            const taskTone = statusTone(task.status);
            return (
              <div class={`star-hud-lane ${taskTone}`}>
                <div class="star-hud-lane-head">
                  <span>{task.description}</span>
                  <span class={`star-hud-pill ${taskTone}`}>{task.status}</span>
                </div>
                <div class="star-hud-handoff">
                  {deps.length ? deps.map((dep) => (
                    <span class="star-hud-pill muted" key={dep?.id}>
                      {`${dep?.id}${dep?.status === 'completed' ? '✓' : ''}`}
                    </span>
                  )) : (
                    <span class="star-hud-pill muted">no deps</span>
                  )}
                </div>
              </div>
            );
          }) : (
            <div class="star-hud-empty">No dependency handoffs yet.</div>
          )}
        </div>
      </div>
      
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
                  ...(slot.faceRight ? { left: `${(slot.left as number) + 10}px` } : { right: `${(slot.right as number) + 10}px` }),
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
                  <div style={{ position: 'absolute', top: '-18px', left: '-10px', fontSize: '8px', color: 'var(--text-primary)', background: 'var(--bg-secondary)', border: '1px solid var(--border)', padding: '0 4px', borderRadius: '2px', fontFamily: 'var(--font-ui)', whiteSpace: 'nowrap', transform: slot.faceRight ? 'none' : 'scaleX(-1)' }}>
                    {agent.id.substring(0,8)}
                  </div>
                  <div style={{ position: 'absolute', top: '-8px', left: '-10px', fontSize: '7px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', whiteSpace: 'nowrap', transform: slot.faceRight ? 'none' : 'scaleX(-1)' }}>
                    {(agent.role || 'worker').toUpperCase()}
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
             <div style={{ position: 'absolute', top: '-18px', left: '-16px', fontSize: '8px', color: 'var(--accent)', background: 'rgba(255, 107, 53, 0.1)', border: '1px solid var(--accent)', padding: '0 4px', borderRadius: '2px', fontFamily: 'var(--font-ui)', whiteSpace: 'nowrap' }}>
               ORCHESTRATOR
             </div>
             {activePlan?.swarm_goal ? (
               <div style={{ position: 'absolute', top: '-34px', left: '-42px', maxWidth: '120px', fontSize: '7px', color: 'var(--text-secondary)', fontFamily: 'var(--font-ui)', textAlign: 'center', lineHeight: 1.2 }}>
                 {activePlan.swarm_goal}
               </div>
             ) : null}
          </div>
        </div>

      </div>
    </div>
  );
}
