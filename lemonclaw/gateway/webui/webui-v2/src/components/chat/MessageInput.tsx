import { useEffect, useRef, useState } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { attachments, abortStream, inputText, isStreaming, messages, retryUploadAttachment, sendMessage, uploadFile, type AttachmentItem } from '../../stores/chat';
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

  const hasUploading = attachments.value.some((item) => item.status === 'uploading');
  const hasFailed = attachments.value.some((item) => item.status === 'failed');
  const readyAttachments = attachments.value.filter((item) => item.status === 'ready');
  const disableSend = isStreaming.value || hasUploading || hasFailed || (!inputText.value.trim() && readyAttachments.length === 0);
  const isFirstTurn = messages.value.length === 0;
  const placeholder = isDragging ? t('drop_files_here') : isFirstTurn ? t('chat_empty_input_placeholder') : t('type_message');

  const attachmentKindLabel = (item: AttachmentItem) => {
    switch (item.kind) {
      case 'image':
        return t('attachment_image');
      case 'video':
        return t('attachment_video');
      case 'audio':
        return t('attachment_audio');
      default:
        return t('attachment_document');
    }
  };

  const attachmentStatusLabel = (item: AttachmentItem) => {
    switch (item.status) {
      case 'uploading':
        return t('attachment_uploading');
      case 'failed':
        return t('attachment_failed');
      default:
        return t('attachment_ready');
    }
  };

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
              <div key={att.id} style={{ position: 'relative', width: isMobile ? '118px' : '132px', borderRadius: '8px', border: '1px solid', borderColor: att.status === 'failed' ? 'rgba(255, 68, 68, 0.35)' : 'var(--border)', overflow: 'hidden', background: 'var(--bg-secondary)' }}>
                <div style={{ height: isMobile ? '58px' : '68px', background: 'var(--bg-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
                  {att.url?.startsWith('data:image') ? (
                    <img src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : att.url?.startsWith('data:video') ? (
                    <video src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} muted autoPlay loop />
                  ) : (
                    <div style={{ padding: '8px', textAlign: 'center', fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {attachmentKindLabel(att)}
                    </div>
                  )}
                  <div style={{ position: 'absolute', left: '6px', bottom: '6px', padding: '2px 6px', borderRadius: '999px', background: 'rgba(0,0,0,0.55)', color: '#fff', fontSize: '9px', fontFamily: 'var(--font-mono)' }}>
                    {attachmentKindLabel(att)}
                  </div>
                  <button onClick={() => removeAttachment(i)} style={{ position: 'absolute', top: '6px', right: '6px', background: 'rgba(0,0,0,0.65)', color: '#fff', border: 'none', borderRadius: '50%', width: '18px', height: '18px', fontSize: '10px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>×</button>
                </div>
                <div style={{ padding: '8px', display: 'grid', gap: '4px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {att.filename}
                  </div>
                  <div style={{ fontSize: '10px', color: att.status === 'failed' ? 'var(--error)' : att.status === 'uploading' ? 'var(--warning)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {attachmentStatusLabel(att)}
                  </div>
                  {att.error ? (
                    <div style={{ fontSize: '10px', color: 'var(--error)', lineHeight: 1.4 }}>
                      {att.error}
                    </div>
                  ) : null}
                  {att.status === 'failed' ? (
                    <button
                      onClick={() => void retryUploadAttachment(att.id)}
                      style={{ marginTop: '2px', padding: '5px 8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '10px', cursor: 'pointer' }}
                    >
                      {t('attachment_retry')}
                    </button>
                  ) : null}
                </div>
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
                  placeholder={placeholder}
                  style={{ flex: 1, minWidth: 0, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px 14px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '14px', resize: 'none', outline: 'none', maxHeight: '160px', minHeight: '42px', lineHeight: '1.5', overflowY: 'auto' }}
                  disabled={isStreaming.value}
                />
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', paddingLeft: '2px' }}>
                {t('composer_hint')}
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
                placeholder={placeholder}
                style={{ flex: 1, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px 14px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '14px', resize: 'none', outline: 'none', maxHeight: '160px', minHeight: '42px', lineHeight: '1.5', overflowY: 'auto' }}
                disabled={isStreaming.value}
              />
              {composerButton}
            </div>
          )}
          {!isMobile && (
            <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', paddingLeft: '52px' }}>
              {t('composer_hint')}
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
