import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { logout } from '../../stores/auth';
import { currentModel, globalDefaultModel, loadModels, models } from '../../stores/models';
import { activeSessionKey, loadSessions, sessions } from '../../stores/sessions';
import { t } from '../../stores/i18n';
import { mobileMenuOpen, showInspector } from '../../stores/ui';
import { modelOptionLabel } from './modelPresentation';

const MOBILE_BREAKPOINT = 768;

export function TopBar() {
  const [showExport, setShowExport] = useState(false);
  const [spOpen, setSpOpen] = useState(false);
  const [spDraft, setSpDraft] = useState('');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [isMobile, setIsMobile] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const isWebUI = activeSessionKey.value.startsWith('webui:');
  const currentSession = sessions.value.find((session) => session.key === activeSessionKey.value);
  useEffect(() => {
    loadModels();
  }, []);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
      }
    };

    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
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
      body: JSON.stringify({ title: titleDraft.trim() }),
    });
    setIsEditingTitle(false);
    loadSessions();
  };

  useEffect(() => {
    setSpOpen(false);
    setSpDraft('');
    if (isWebUI && activeSessionKey.value) {
      apiFetch(`/api/sessions/${activeSessionKey.value}/messages`, { silent404: true })
        .then((res) => res.json())
        .then((data) => {
          if (data.system_prompt_override) setSpDraft(data.system_prompt_override);
        })
        .catch(() => {});
    }
  }, [activeSessionKey.value]);

  const handleSpSave = async (text: string) => {
    await apiFetch(`/api/sessions/${activeSessionKey.value}`, {
      method: 'PATCH',
      body: JSON.stringify({ system_prompt_override: text }),
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

  const title = currentSession?.title?.trim() || t('unnamed_chat');
  const compactActionPadding = isMobile ? '0 10px' : '0 8px';
  const compactActionHeight = isMobile ? '40px' : '32px';

  return (
    <div class="topbar-root" style={{ position: isMobile ? 'sticky' : 'relative', top: isMobile ? 0 : undefined, left: 0, right: 0, display: 'flex', flexDirection: 'column', flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-primary)', zIndex: 20, backdropFilter: isMobile ? 'saturate(120%) blur(8px)' : undefined, WebkitBackdropFilter: isMobile ? 'saturate(120%) blur(8px)' : undefined }}>
      <div style={{ minHeight: isMobile ? '56px' : 'var(--topbar-h)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: isMobile ? '8px' : '12px', padding: isMobile ? '8px 10px' : '0 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '8px' : '12px', minWidth: 0, flex: 1 }}>
          <button class="topbar-mobile-btn" onClick={() => mobileMenuOpen.value = true} style={{ background: 'transparent', border: '1px solid transparent', color: 'var(--text-primary)', fontSize: '18px', cursor: 'pointer', padding: isMobile ? '8px' : '0 8px', marginRight: isMobile ? 0 : '4px', flexShrink: 0, minWidth: isMobile ? '40px' : 'auto', minHeight: isMobile ? '40px' : 'auto', height: isMobile ? compactActionHeight : 'auto', width: isMobile ? '40px' : 'auto', borderRadius: isMobile ? '10px' : '0', touchAction: 'manipulation' }}>☰</button>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: '4px', minWidth: 0, flex: 1 }}>
            <span class="topbar-session-id">{t('session_label')}</span>
            {isEditingTitle ? (
              <input
                ref={titleInputRef}
                value={titleDraft}
                onInput={(e) => setTitleDraft((e.target as HTMLInputElement).value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleTitleSave(); if (e.key === 'Escape') setIsEditingTitle(false); }}
                onBlur={handleTitleSave}
                style={{ background: 'var(--bg-secondary)', border: '1px solid var(--accent)', color: 'var(--text-primary)', padding: isMobile ? '6px 8px' : '2px 6px', borderRadius: '4px', fontSize: isMobile ? '13px' : '12px', fontFamily: 'var(--font-mono)', outline: 'none', minWidth: 0, width: isMobile ? '100%' : 'auto', minHeight: isMobile ? '40px' : 'auto' }}
              />
            ) : (
              <span
                style={{ color: 'var(--text-primary)', cursor: isWebUI ? 'pointer' : 'default', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                onClick={() => { if (isWebUI) { setTitleDraft(currentSession?.title || ''); setIsEditingTitle(true); } }}
                onDblClick={() => isWebUI && setSpOpen(!spOpen)}
                title={t('rename_session')}
              >
                {title}
              </span>
            )}
          </div>
          {isWebUI && spDraft && (
            <button
              onClick={() => setSpOpen(!spOpen)}
              style={{ fontSize: '11px', color: 'var(--accent)', fontFamily: 'var(--font-mono)', border: '1px solid var(--accent)', padding: isMobile ? '0 8px' : '0 4px', cursor: 'pointer', background: 'transparent', flexShrink: 0, minHeight: compactActionHeight, borderRadius: '6px', touchAction: 'manipulation' }}
            >
              {t('session_prompt_button')}
            </button>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '6px' : '8px', flexShrink: 0 }}>
          {!isMobile && isWebUI && (
            <>
              <select
                value={currentModel.value}
                onChange={(e) => currentModel.value = (e.target as HTMLSelectElement).value}
                style={{ maxWidth: '240px', textOverflow: 'ellipsis', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--teal)', outline: 'none', cursor: 'pointer' }}
              >
                {models.value.length === 0 && <option value={currentModel.value}>{currentModel.value || 'Loading...'}</option>}
                {models.value.map((model) => <option key={model.id} value={model.id}>{modelOptionLabel(model, t)}</option>)}
              </select>
            </>
          )}

          <div ref={exportRef} style={{ position: 'relative' }}>
            <button onClick={() => setShowExport(!showExport)} title={t('export_chat')} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', minWidth: isMobile ? compactActionHeight : 'auto', minHeight: compactActionHeight, padding: compactActionPadding, fontFamily: 'var(--font-mono)', fontSize: isMobile ? '13px' : '11px', color: 'var(--text-secondary)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', touchAction: 'manipulation' }}>📦 <span class="topbar-text-label">{t('export_chat')} ▼</span></button>
            {showExport && (
              <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '6px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '4px', zIndex: 100, display: 'flex', flexDirection: 'column', gap: '2px', width: isMobile ? 'calc(100vw - 24px)' : '120px', minWidth: isMobile ? '160px' : '120px', maxWidth: isMobile ? '180px' : '120px', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
                <button onClick={() => doExport('md')} style={{ padding: '8px', textAlign: isMobile ? 'center' : 'left', background: 'transparent', border: 'none', color: 'var(--text-primary)', fontSize: isMobile ? '12px' : '11px', fontFamily: 'var(--font-mono)', cursor: 'pointer', borderRadius: '2px', minHeight: '34px' }} onMouseEnter={(e) => { if (!isMobile) e.currentTarget.style.background='var(--bg-hover)'; }} onMouseLeave={(e) => { if (!isMobile) e.currentTarget.style.background='transparent'; }}>{t('export_md')}</button>
                <button onClick={() => doExport('json')} style={{ padding: '8px', textAlign: isMobile ? 'center' : 'left', background: 'transparent', border: 'none', color: 'var(--text-primary)', fontSize: isMobile ? '12px' : '11px', fontFamily: 'var(--font-mono)', cursor: 'pointer', borderRadius: '2px', minHeight: '34px' }} onMouseEnter={(e) => { if (!isMobile) e.currentTarget.style.background='var(--bg-hover)'; }} onMouseLeave={(e) => { if (!isMobile) e.currentTarget.style.background='transparent'; }}>{t('export_json')}</button>
              </div>
            )}
          </div>

          <button onClick={logout} title={t('logout')} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', minWidth: isMobile ? compactActionHeight : 'auto', minHeight: compactActionHeight, padding: compactActionPadding, fontFamily: 'var(--font-mono)', fontSize: isMobile ? '13px' : '11px', color: 'var(--error)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', touchAction: 'manipulation' }}>🚪 <span class="topbar-text-label">{t('logout')}</span></button>

          <button onClick={() => showInspector.value = !showInspector.value} style={{ background: showInspector.value ? 'var(--bg-tertiary)' : 'transparent', border: '1px solid var(--border)', borderRadius: '4px', minWidth: isMobile ? compactActionHeight : 'auto', minHeight: compactActionHeight, padding: compactActionPadding, fontFamily: 'var(--font-mono)', fontSize: isMobile ? '13px' : '11px', color: 'var(--text-primary)', cursor: 'pointer', marginLeft: isMobile ? '0' : '8px', transition: 'all 0.2s', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '4px', touchAction: 'manipulation' }} title={t('toggle_inspector')}>
            👁️ <span class="topbar-text-label">{t('open_side_panel')}</span>
          </button>
        </div>
      </div>

      {isMobile && isWebUI && (
        <div style={{ padding: '0 12px 10px', display: 'flex' }}>
          <select
            value={currentModel.value}
            onChange={(e) => currentModel.value = (e.target as HTMLSelectElement).value}
            style={{ width: '100%', minWidth: 0, textOverflow: 'ellipsis', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--teal)', outline: 'none', cursor: 'pointer' }}
          >
            {models.value.length === 0 && <option value={currentModel.value}>{currentModel.value || 'Loading...'}</option>}
            {models.value.map((model) => <option key={model.id} value={model.id}>{modelOptionLabel(model, t)}</option>)}
          </select>
        </div>
      )}

      {spOpen && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, padding: isMobile ? '12px' : '16px', background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '12px', boxShadow: '0 10px 30px rgba(0,0,0,0.5)', zIndex: 100, animation: 'slideUpFade 0.2s ease-out', maxHeight: isMobile ? '50dvh' : 'none', overflowY: 'auto' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>{t('sp_placeholder')}</div>
          <textarea
            value={spDraft}
            onInput={(e) => setSpDraft((e.target as HTMLTextAreaElement).value)}
            style={{ width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '4px', padding: '10px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', resize: 'vertical', minHeight: isMobile ? '96px' : '120px' }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', flexWrap: 'wrap' }}>
            <button onClick={() => { setSpDraft(''); handleSpSave(''); }} style={{ padding: '6px 16px', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>{t('sp_clear')}</button>
            <button onClick={() => handleSpSave(spDraft)} style={{ padding: '6px 16px', background: 'var(--accent)', border: 'none', borderRadius: '4px', color: '#fff', cursor: 'pointer', fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>{t('sp_save')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
