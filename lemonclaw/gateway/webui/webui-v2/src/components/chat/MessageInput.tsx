import { useEffect, useRef, useState } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { attachments, abortStream, inputText, isStreaming, sendMessage, uploadFile } from '../../stores/chat';
import { t } from '../../stores/i18n';

const MOBILE_BREAKPOINT = 640;

export function MessageInput() {
  const [isDragging, setIsDragging] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isWebUI = activeSessionKey.value.startsWith('webui:');
  if (!isWebUI) return null;

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

  const handleInput = (e: Event) => {
    const target = e.target as HTMLTextAreaElement;
    inputText.value = target.value;
    target.style.height = 'auto';
    target.style.height = `${Math.min(target.scrollHeight, 160)}px`;
  };

  const submit = () => {
    if ((!inputText.value.trim() && attachments.value.length === 0) || isStreaming.value) return;
    sendMessage(inputText.value.trim());
    inputText.value = '';
    if (textareaRef.current) textareaRef.current.style.height = '42px';
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer?.files) {
      Array.from(e.dataTransfer.files).forEach((file) => uploadFile(file));
    }
  };

  const removeAttachment = (index: number) => {
    attachments.value = attachments.value.filter((_, i) => i !== index);
  };

  const disableSend = isStreaming.value || (!inputText.value.trim() && attachments.value.length === 0);

  const composerButton = isStreaming.value ? (
    <button onClick={abortStream} style={{ background: 'transparent', color: 'var(--error)', border: '1px solid var(--error)', borderRadius: '8px', padding: isMobile ? '0 16px' : '0 20px', height: '42px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontWeight: 600, width: isMobile ? '100%' : 'auto' }}>
      {t('stop')}
    </button>
  ) : (
    <button onClick={submit} disabled={disableSend} style={{ background: disableSend ? 'var(--bg-tertiary)' : 'var(--accent)', color: '#fff', border: 'none', borderRadius: '8px', padding: isMobile ? '0 16px' : '0 20px', height: '42px', cursor: disableSend ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-mono)', fontWeight: 600, opacity: disableSend ? 0.5 : 1, width: isMobile ? '100%' : 'auto' }}>
      {t('send')}
    </button>
  );

  return (
    <div style={{ padding: isMobile ? '12px 12px calc(12px + env(safe-area-inset-bottom))' : '16px', borderTop: '1px solid var(--border)', background: 'var(--bg-primary)' }}>
      <div style={{ maxWidth: '800px', margin: '0 auto' }}>
        {attachments.value.length > 0 && (
          <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
            {attachments.value.map((att, i) => (
              <div key={i} style={{ position: 'relative', width: isMobile ? '52px' : '60px', height: isMobile ? '52px' : '60px', borderRadius: '6px', border: '1px solid var(--border)', overflow: 'hidden', background: 'var(--bg-secondary)' }}>
                {att.url?.startsWith('data:image') ? <img src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : att.url?.startsWith('data:video') ? <video src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} muted autoPlay loop /> : <div style={{ padding: '4px', fontSize: '10px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>{att.filename}</div>}
                <button onClick={() => removeAttachment(i)} style={{ position: 'absolute', top: '2px', right: '2px', background: 'var(--error)', color: '#fff', border: 'none', borderRadius: '50%', width: '16px', height: '16px', fontSize: '10px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>×</button>
              </div>
            ))}
          </div>
        )}

        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          style={{ border: isDragging ? '1px dashed var(--accent)' : '1px solid transparent', borderRadius: '12px', padding: isDragging ? '4px' : '0', transition: 'all 0.2s' }}
        >
          {isMobile ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                <button onClick={() => fileInputRef.current?.click()} style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', width: '42px', height: '42px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-muted)', flexShrink: 0 }}>
                  📎
                </button>
                <textarea
                  ref={textareaRef}
                  value={inputText.value}
                  onInput={handleInput}
                  onKeyDown={handleKeyDown}
                  placeholder={isDragging ? t('drop_files_here') : t('type_message')}
                  style={{ flex: 1, minWidth: 0, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px 14px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '14px', resize: 'none', outline: 'none', maxHeight: '160px', minHeight: '42px', lineHeight: '1.5', overflowY: 'auto' }}
                  disabled={isStreaming.value}
                />
              </div>
              {composerButton}
            </div>
          ) : (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
              <button onClick={() => fileInputRef.current?.click()} style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', width: '42px', height: '42px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-muted)' }}>
                📎
              </button>
              <textarea
                ref={textareaRef}
                value={inputText.value}
                onInput={handleInput}
                onKeyDown={handleKeyDown}
                placeholder={isDragging ? t('drop_files_here') : t('type_message')}
                style={{ flex: 1, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px 14px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '14px', resize: 'none', outline: 'none', maxHeight: '160px', minHeight: '42px', lineHeight: '1.5', overflowY: 'auto' }}
                disabled={isStreaming.value}
              />
              {composerButton}
            </div>
          )}

          <input type="file" ref={fileInputRef} style={{ display: 'none' }} multiple onChange={(e) => {
            if (e.target instanceof HTMLInputElement && e.target.files) {
              Array.from(e.target.files).forEach((file) => uploadFile(file));
            }
            if (fileInputRef.current) fileInputRef.current.value = '';
          }} />
        </div>
      </div>
    </div>
  );
}
