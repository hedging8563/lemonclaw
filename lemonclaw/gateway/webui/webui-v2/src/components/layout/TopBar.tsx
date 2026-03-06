import { useState, useRef, useEffect } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { currentModel, models, loadModels, globalDefaultModel } from '../../stores/models';
import { logout } from '../../stores/auth';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';
import { showInspector, mobileMenuOpen } from '../../stores/ui';

import { sessions, loadSessions } from '../../stores/sessions';

export function TopBar() {
  const [showExport, setShowExport] = useState(false);
  const [spOpen, setSpOpen] = useState(false);
  const [spDraft, setSpDraft] = useState('');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const exportRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const isWebUI = activeSessionKey.value.startsWith('webui:');
  const currentSession = sessions.value.find(s => s.key === activeSessionKey.value);

  useEffect(() => {
    loadModels();
  }, []);

  useEffect(() => {
    if (currentSession && currentSession.model) {
      currentModel.value = currentSession.model;
    } else if (globalDefaultModel.value) {
      currentModel.value = globalDefaultModel.value;
    }
  }, [activeSessionKey.value, currentSession?.model, globalDefaultModel.value]);

  useEffect(() => {
    if (isEditingTitle) titleInputRef.current?.focus();
  }, [isEditingTitle]);

  const handleTitleSave = async () => {
    if (!titleDraft.trim() || titleDraft === currentSession?.title) {
      setIsEditingTitle(false);
      return;
    }
    await apiFetch(`/api/sessions/${activeSessionKey.value}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: titleDraft.trim() })
    });
    setIsEditingTitle(false);
    loadSessions();
  };

  useEffect(() => {
    setSpOpen(false);
    setSpDraft('');
    if (isWebUI && activeSessionKey.value) {
      apiFetch(`/api/sessions/${activeSessionKey.value}/messages`, { silent404: true })
        .then(res => res.json())
        .then(data => {
          if (data.system_prompt_override) setSpDraft(data.system_prompt_override);
        })
        .catch(() => {});
    }
  }, [activeSessionKey.value]);

  const handleSpSave = async (text: string) => {
    await apiFetch(`/api/sessions/${activeSessionKey.value}`, {
      method: 'PATCH',
      body: JSON.stringify({ system_prompt_override: text })
    });
    setSpDraft(text);
    if (!text) setSpOpen(false);
  };

  const doExport = (fmt: string) => {
    window.open(`/api/sessions/${activeSessionKey.value}/export?format=${fmt}`, '_blank');
    setShowExport(false);
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setShowExport(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', zIndex: 20 }}>
      <div style={{ height: 'var(--topbar-h)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
          <button class="topbar-mobile-btn" onClick={() => mobileMenuOpen.value = true} style={{ background: 'transparent', border: 'none', color: 'var(--text-primary)', fontSize: '18px', cursor: 'pointer', paddingRight: '8px' }}>☰</button>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span class="topbar-session-id">{t('session_label')}</span>
            {isEditingTitle ? (
              <input 
                ref={titleInputRef}
                value={titleDraft}
                onInput={e => setTitleDraft((e.target as HTMLInputElement).value)}
                onKeyDown={e => { if(e.key === 'Enter') handleTitleSave(); if(e.key === 'Escape') setIsEditingTitle(false); }}
                onBlur={handleTitleSave}
                style={{ background: 'var(--bg-secondary)', border: '1px solid var(--accent)', color: 'var(--text-primary)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--font-mono)', outline: 'none' }}
              />
            ) : (
              <span 
                style={{ color: 'var(--text-primary)', cursor: isWebUI ? 'pointer' : 'default' }} 
                onClick={() => { if(isWebUI) { setTitleDraft(currentSession?.title || ''); setIsEditingTitle(true); } }}
                onDblClick={() => isWebUI && setSpOpen(!spOpen)}
                title={t('click_edit_sp')}
              >
                {currentSession?.title || activeSessionKey.value.replace('webui:', '')}
              </span>
            )}
          </div>
          {isWebUI && spDraft && <span style={{ fontSize: '10px', color: 'var(--accent)', fontFamily: 'var(--font-mono)', border: '1px solid var(--accent)', padding: '0 4px', borderRadius: '3px', cursor: 'pointer' }} onClick={() => setSpOpen(!spOpen)}>SP</span>}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {isWebUI && (
            <select 
              value={currentModel.value}
              onChange={(e) => currentModel.value = (e.target as HTMLSelectElement).value}
              style={{ maxWidth: '240px', textOverflow: 'ellipsis', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--teal)', outline: 'none', cursor: 'pointer' }}
            >
              {models.value.length === 0 && <option value={currentModel.value}>{currentModel.value || 'Loading...'}</option>}
              {models.value.map(m => <option key={m.id} value={m.id}>{m.id.split('/').pop()}</option>)}
            </select>
          )}

          <div ref={exportRef} style={{ position: 'relative' }}>
            <button onClick={() => setShowExport(!showExport)} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', cursor: 'pointer' }}>📦 <span class="topbar-text-label">{t('export')} ▼</span></button>
            {showExport && (
              <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '4px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px', zIndex: 100, display: 'flex', flexDirection: 'column', gap: '2px', width: '120px', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
                <button onClick={() => doExport('md')} style={{ padding: '6px', textAlign: 'left', background: 'transparent', border: 'none', color: 'var(--text-primary)', fontSize: '11px', fontFamily: 'var(--font-mono)', cursor: 'pointer', borderRadius: '2px' }} onMouseEnter={e => e.currentTarget.style.background='var(--bg-hover)'} onMouseLeave={e => e.currentTarget.style.background='transparent'}>{t('export_md')}</button>
                <button onClick={() => doExport('json')} style={{ padding: '6px', textAlign: 'left', background: 'transparent', border: 'none', color: 'var(--text-primary)', fontSize: '11px', fontFamily: 'var(--font-mono)', cursor: 'pointer', borderRadius: '2px' }} onMouseEnter={e => e.currentTarget.style.background='var(--bg-hover)'} onMouseLeave={e => e.currentTarget.style.background='transparent'}>{t('export_json')}</button>
              </div>
            )}
          </div>

          <button onClick={logout} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--error)', cursor: 'pointer' }}>🚪 <span class="topbar-text-label">{t('logout')}</span></button>
          
          <button onClick={() => showInspector.value = !showInspector.value} style={{ background: showInspector.value ? 'var(--bg-tertiary)' : 'transparent', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-primary)', cursor: 'pointer', marginLeft: '8px', transition: 'all 0.2s' }} title={t('toggle_inspector')}>
            👁️
          </button>
        </div>
      </div>

      {spOpen && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, padding: '16px', background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '12px', boxShadow: '0 10px 30px rgba(0,0,0,0.5)', zIndex: 100, animation: 'slideUpFade 0.2s ease-out' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>{t('sp_placeholder')}</div>
          <textarea 
            value={spDraft}
            onInput={(e) => setSpDraft((e.target as HTMLTextAreaElement).value)}
            style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '10px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', resize: 'vertical', minHeight: '120px' }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <button onClick={() => { setSpDraft(''); handleSpSave(''); }} style={{ padding: '6px 16px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>{t('sp_clear')}</button>
            <button onClick={() => handleSpSave(spDraft)} style={{ padding: '6px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>{t('sp_save')}</button>
          </div>
        </div>
      )}
    </div>
  );
}