import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { SkillsTab } from './SkillsTab';
import { t } from '../../stores/i18n';

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<any>(null);
  const [draft, setDraft] = useState<any>(null);
  const [changedPaths, setChangedPaths] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState('providers');

  const load = async () => {
    try {
      const res = await apiFetch('/api/settings');
      const data = await res.json();
      setSettings(data.settings);
      setDraft(JSON.parse(JSON.stringify(data.settings)));
      setChangedPaths(new Set());
    } catch (e) {
      console.error("Failed to load settings", e);
    }
  };

  useEffect(() => { load(); }, []);

  const handleChange = (path: string[], value: any) => {
    let obj = draft;
    for (let i = 0; i < path.length - 1; i++) {
      if (!obj[path[i]]) obj[path[i]] = {};
      obj = obj[path[i]];
    }
    obj[path[path.length - 1]] = value;
    setDraft({ ...draft });
    
    const topPath = path[0] === 'agents' ? 'agents.defaults.' + path[2] : path[0] + '.' + path[1];
    setChangedPaths(new Set(changedPaths).add(topPath));
  };

  const handleSave = async () => {
    if (changedPaths.size === 0) return onClose();
    
    const payload: any = {};
    for (const p of Array.from(changedPaths)) {
      if (p.startsWith('agents.defaults.')) {
        const key = p.replace('agents.defaults.', '');
        payload[p] = draft.agents.defaults[key];
      } else {
        const [cat, key] = p.split('.');
        payload[p] = draft[cat][key];
      }
    }

    try {
      await apiFetch('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) });
      const applyRes = await apiFetch('/api/settings/apply', { method: 'POST', body: JSON.stringify({ changed_paths: Array.from(changedPaths) }) });
      const applyData = await applyRes.json();
      if (applyData.restart_required) {
        // Instead of a blocking alert, just log or use a mild prompt
        console.log('Backend is restarting to apply changes.');
      }
      onClose();
    } catch (e: any) {
      console.error('Save failed: ', e);
    }
  };

  const renderFields = (data: any, path: string[]) => {
    if (!data) return null;
    return Object.entries(data).map(([k, v]) => {
      const currentPath = [...path, k];
      if (Array.isArray(v)) {
         return (
           <div key={k} style={{ marginBottom: '12px' }}>
             <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{k}</label>
             <input type="text" value={v.join(', ')} onInput={(e) => handleChange(currentPath, (e.target as any).value.split(',').map((s:string)=>s.trim()))} style={{ width:'100%', background:'var(--bg-primary)', border:'1px solid var(--border)', color:'var(--text-primary)', padding:'8px 10px', borderRadius:'4px', fontFamily:'var(--font-mono)', fontSize:'12px', outline: 'none' }} />
           </div>
         );
      } else if (typeof v === 'object' && v !== null) {
         let currentObj = v;
         let displayKey = k;
         let cPath = [...currentPath];
         while (typeof currentObj === 'object' && currentObj !== null && !Array.isArray(currentObj)) {
           const keys = Object.keys(currentObj);
           if (keys.length === 1 && typeof currentObj[keys[0]] === 'object' && currentObj[keys[0]] !== null && !Array.isArray(currentObj[keys[0]])) {
             displayKey += '.' + keys[0];
             cPath.push(keys[0]);
             currentObj = currentObj[keys[0]];
           } else {
             break;
           }
         }
         return (
           <div key={displayKey} style={{ marginBottom: '16px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '16px' }}>
             <div style={{ fontSize: '14px', color: 'var(--accent)', marginBottom: '16px', fontFamily: 'var(--font-mono)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
               <span style={{ color: 'var(--purple)' }}>#</span> {displayKey}
             </div>
             {renderFields(currentObj, cPath)}
           </div>
         );
      } else if (typeof v === 'boolean') {
         return (
           <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
             <input type="checkbox" checked={v} onChange={e => handleChange(currentPath, (e.target as any).checked)} />
             <label style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{k}</label>
           </div>
         );
      } else if (typeof v === 'number') {
         return (
           <div key={k} style={{ marginBottom: '12px' }}>
             <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom:'4px', fontFamily: 'var(--font-mono)' }}>{k}</label>
             <input type="number" value={v as number} onInput={e => handleChange(currentPath, Number((e.target as any).value))} style={{ width:'100%', background:'var(--bg-primary)', border:'1px solid var(--border)', color:'var(--text-primary)', padding:'8px 10px', borderRadius:'4px', fontFamily:'var(--font-mono)', fontSize:'12px', outline: 'none' }} />
           </div>
         );
      } else {
         const isSecret = k.includes('key') || k.includes('token') || k.includes('secret');
         return (
           <div key={k} style={{ marginBottom: '12px' }}>
             <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom:'4px', fontFamily: 'var(--font-mono)' }}>{k}</label>
             <input type={isSecret ? 'password' : 'text'} value={v as string} onInput={e => handleChange(currentPath, (e.target as any).value)} style={{ width:'100%', background:'var(--bg-primary)', border:'1px solid var(--border)', color:'var(--text-primary)', padding:'8px 10px', borderRadius:'4px', fontFamily:'var(--font-mono)', fontSize:'12px', outline: 'none' }} />
           </div>
         );
      }
    });
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(4px)' }}>
      <div style={{ width: '95%', maxWidth: '1100px', height: '85vh', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,0.6)' }}>
        
        {/* Header */}
        <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', color: 'var(--text-primary)', letterSpacing: '1px' }}>
            <span style={{ color: 'var(--purple)' }}>//</span> {t('settings_title')}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '24px', cursor: 'pointer', lineHeight: 1 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* Tabs */}
          <div style={{ width: '200px', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '6px', padding: '16px' }}>
            {['providers', 'agents', 'channels', 'tools', 'skills'].map(tab => (
              <button 
                key={tab}
                onClick={() => setActiveTab(tab)}
                style={{ 
                  textAlign: 'left', padding: '10px 12px', 
                  background: activeTab === tab ? 'var(--bg-tertiary)' : 'transparent', 
                  color: activeTab === tab ? 'var(--accent)' : 'var(--text-muted)', 
                  border: '1px solid', borderColor: activeTab === tab ? 'var(--border)' : 'transparent', 
                  borderRadius: '6px', fontFamily: 'var(--font-mono)', fontSize: '12px', 
                  textTransform: 'uppercase', cursor: 'pointer', transition: 'all 0.2s'
                }}
              >
                {(t as any)(`tab_${tab}`)}
              </button>
            ))}
          </div>

          {/* Content Area */}
          <div style={{ flex: 1, padding: '32px', overflowY: 'auto', background: 'var(--bg-primary)' }}>
            {!draft ? <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{t('loading_configs')}</div> : (
              <div style={{ animation: 'fadeIn 0.3s ease-out' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '20px', color: 'var(--text-primary)', marginBottom: '8px', textTransform: 'capitalize' }}>
                  {(t as any)(`tab_${activeTab}`)}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '32px' }}>
                  {t('settings_desc')}
                </div>
                
                {activeTab === 'skills' ? <SkillsTab /> : renderFields(draft[activeTab], [activeTab])}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', gap: '12px', background: 'var(--bg-secondary)' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {changedPaths.size > 0 && <span style={{ color: 'var(--accent)' }}>● {changedPaths.size} {t('unsaved_changes')}</span>}
          </div>
          <button onClick={onClose} style={{ padding: '8px 24px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-primary)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>{t('btn_cancel')}</button>
          <button onClick={handleSave} disabled={changedPaths.size === 0} style={{ padding: '8px 24px', background: changedPaths.size === 0 ? 'var(--bg-tertiary)' : 'var(--accent)', border: 'none', borderRadius: '6px', color: '#fff', cursor: changedPaths.size === 0 ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 'bold' }}>{t('btn_save_apply')}</button>
        </div>
      </div>
    </div>
  );
}