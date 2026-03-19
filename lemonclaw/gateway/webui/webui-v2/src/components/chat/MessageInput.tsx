import { useEffect, useRef, useState } from 'preact/hooks';
import { activeSessionKey } from '../../stores/sessions';
import { attachments, abortStream, inputText, isStreaming, messages, retryUploadAttachment, sendMessage, uploadFile, type AttachmentItem } from '../../stores/chat';
import { t } from '../../stores/i18n';

const MOBILE_BREAKPOINT = 640;

function formatFileSize(bytes?: number) {
  const size = Number(bytes || 0);
  if (!size) return '—';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIcon(kind: AttachmentItem['kind']) {
  switch (kind) {
    case 'image':
      return '🖼';
    case 'video':
      return '🎞';
    case 'audio':
      return '🎧';
    default:
      return '📄';
  }
}

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

  const removeAttachment = (id: string) => {
    attachments.value = attachments.value.filter((item) => item.id !== id);
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

  const attachmentStatusColor = (item: AttachmentItem) => {
    if (item.status === 'failed') return 'var(--error)';
    if (item.status === 'uploading') return 'var(--accent)';
    return 'var(--success)';
  };

  const composerStatusText = hasUploading
    ? t('attachment_uploading')
    : hasFailed
      ? t('attachment_failed')
      : t('composer_hint');
  const attachmentQueueStatus = t('attachment_queue_status')
    .replace('{ready}', String(readyAttachments.length))
    .replace('{total}', String(attachments.value.length));

  const composerButton = isStreaming.value ? (
    <button onClick={abortStream} style={{ background: 'transparent', color: 'var(--error)', border: '1px solid var(--error)', borderRadius: '10px', padding: isMobile ? '0 16px' : '0 20px', minHeight: '44px', cursor: 'pointer', fontFamily: 'var(--font-ui)', fontWeight: 600, width: isMobile ? '100%' : 'auto' }}>
      {t('stop')}
    </button>
  ) : (
    <button onClick={submit} disabled={disableSend} style={{ background: disableSend ? 'var(--bg-tertiary)' : 'var(--text-primary)', color: disableSend ? 'var(--text-primary)' : 'var(--bg-primary)', border: 'none', borderRadius: '12px', padding: isMobile ? '0 16px' : '0 24px', minHeight: '44px', cursor: disableSend ? 'not-allowed' : 'pointer', fontFamily: 'var(--font-ui)', fontWeight: 600, opacity: 1, width: isMobile ? '100%' : 'auto', transition: 'all 0.2s' }}>
      {t('send')}
    </button>
  );

  return (
    <div style={{ position: 'sticky', bottom: 0, padding: isMobile ? '12px 12px calc(12px + env(safe-area-inset-bottom))' : '16px 32px 24px', background: 'var(--bg-primary)', zIndex: 100 }}>
      <div style={{ maxWidth: '840px', margin: '0 auto', padding: isMobile ? '0 10px' : '0 16px' }}>
        {attachments.value.length > 0 && (
          <div style={{ marginBottom: '16px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '16px', padding: isMobile ? '10px' : '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', marginBottom: '10px' }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: 'var(--font-ui)', fontSize: '15px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>
                  {t('attachment_queue_title')}
                </div>
                <div style={{ fontSize: '15px', color: 'var(--text-secondary)' }}>
                  {attachmentQueueStatus}
                </div>
              </div>
              <button onClick={() => { attachments.value = []; }} style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: '999px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', fontSize: '15px', padding: '6px 10px', cursor: 'pointer' }}>
                {t('common_clear')}
              </button>
            </div>
            <div style={{ display: isMobile ? 'flex' : 'grid', gap: '10px', gridTemplateColumns: isMobile ? undefined : 'repeat(auto-fit, minmax(180px, 1fr))', overflowX: isMobile ? 'auto' : 'visible', paddingBottom: isMobile ? '2px' : 0 }}>
              {attachments.value.map((att) => (
                <div key={att.id} style={{ position: 'relative', borderRadius: '14px', border: '1px solid', borderColor: att.status === 'failed' ? 'rgba(255, 68, 68, 0.35)' : att.status === 'uploading' ? 'rgba(255, 107, 53, 0.28)' : 'var(--border)', overflow: 'hidden', background: 'var(--bg-primary)', flex: isMobile ? '0 0 220px' : undefined, minWidth: isMobile ? '220px' : 0 }}>
                  <div style={{ height: isMobile ? '110px' : '124px', background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.01) 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
                    {att.url?.startsWith('data:image') ? (
                      <img src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : att.url?.startsWith('data:video') ? (
                      <video src={att.url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} muted autoPlay loop />
                    ) : (
                      <div style={{ display: 'grid', gap: '8px', placeItems: 'center', color: 'var(--text-muted)' }}>
                        <div style={{ fontSize: '28px' }}>{attachmentIcon(att.kind)}</div>
                        <div style={{ fontSize: '15px', fontFamily: 'var(--font-ui)' }}>{attachmentKindLabel(att)}</div>
                      </div>
                    )}
                    <div style={{ position: 'absolute', left: '10px', bottom: '10px', display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 8px', borderRadius: '999px', background: 'rgba(0,0,0,0.58)', color: '#fff', fontSize: '15px', fontFamily: 'var(--font-ui)' }}>
                      <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: attachmentStatusColor(att) }} />
                      {attachmentStatusLabel(att)}
                    </div>
                    <button onClick={() => removeAttachment(att.id)} style={{ position: 'absolute', top: '10px', right: '10px', background: 'rgba(0,0,0,0.66)', color: '#fff', border: 'none', borderRadius: '999px', minWidth: '24px', height: '24px', fontSize: '15px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>×</button>
                  </div>
                  <div style={{ padding: '10px', display: 'grid', gap: '8px' }}>
                    <div style={{ display: 'grid', gap: '4px' }}>
                      <div style={{ fontSize: '15px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {att.filename}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', fontSize: '15px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)' }}>
                        <span>{attachmentKindLabel(att)}</span>
                        <span>{formatFileSize(att.file?.size)}</span>
                      </div>
                    </div>
                    {att.error ? (
                      <div style={{ fontSize: '15px', color: 'var(--error)', lineHeight: 1.45, minHeight: '28px' }}>
                        {att.error}
                      </div>
                    ) : (
                      <div style={{ fontSize: '15px', color: 'var(--text-muted)', lineHeight: 1.45, minHeight: '28px' }}>
                        {att.status === 'ready' ? t('attachment_ready') : attachmentStatusLabel(att)}
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                      {att.status === 'failed' ? (
                        <button
                          onClick={() => void retryUploadAttachment(att.id)}
                          style={{ padding: '7px 10px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-secondary)', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: 'pointer' }}
                        >
                          {t('attachment_retry')}
                        </button>
                      ) : <span />}
                      <button onClick={() => removeAttachment(att.id)} style={{ padding: '7px 10px', borderRadius: '999px', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: 'pointer' }}>
                        {t('common_remove')}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          style={{ border: isDragging ? '1px dashed var(--accent)' : '1px solid transparent', borderRadius: '16px', padding: isDragging ? '4px' : '0', transition: 'all 0.2s' }}
        >
          {isMobile ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '16px', padding: '10px', boxShadow: '0 14px 30px rgba(0,0,0,0.16)' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                <button onClick={() => fileInputRef.current?.click()} style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '12px', width: '44px', height: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-muted)', flexShrink: 0 }}>
                  📎
                </button>
                <textarea
                  ref={textareaRef}
                  value={inputText.value}
                  onInput={handleInput}
                  onKeyDown={handleKeyDown}
                  placeholder={placeholder}
                  style={{ flex: 1, minWidth: 0, background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '12px', padding: '12px 14px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '15px', resize: 'none', outline: 'none', maxHeight: '160px', minHeight: '44px', lineHeight: '1.5', overflowY: 'auto' }}
                  disabled={isStreaming.value}
                />
              </div>
              <div style={{ fontSize: '15px', color: hasFailed ? 'var(--error)' : hasUploading ? 'var(--accent)' : 'var(--text-muted)', fontFamily: 'var(--font-ui)', paddingLeft: '2px' }}>
                {composerStatusText}
              </div>
              {composerButton}
            </div>
          ) : (
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', background: 'var(--bg-tertiary)', borderRadius: '20px', padding: '8px', boxShadow: '0 8px 32px rgba(0,0,0,0.08)' }}>
              <button onClick={() => fileInputRef.current?.click()} style={{ background: 'var(--bg-secondary)', border: 'none', borderRadius: '12px', width: '44px', height: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-muted)', transition: 'all 0.2s', flexShrink: 0 }} onMouseEnter={e => { e.currentTarget.style.color='var(--text-primary)'; e.currentTarget.style.borderColor='var(--text-muted)'; }} onMouseLeave={e => { e.currentTarget.style.color='var(--text-secondary)'; e.currentTarget.style.borderColor='var(--border)'; }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
              </button>
              <textarea
                ref={textareaRef}
                value={inputText.value}
                onInput={handleInput}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                style={{ flex: 1, background: 'var(--bg-secondary)', border: 'none', borderRadius: '12px', padding: '12px 16px', color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', fontSize: '15px', resize: 'none', outline: 'none', maxHeight: '200px', minHeight: '44px', lineHeight: '1.5', overflowY: 'auto', transition: 'border-color 0.2s' }}
                disabled={isStreaming.value}
              />
              {composerButton}
            </div>
          )}
          {!isMobile && (
            <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'space-between', paddingLeft: '64px', paddingRight: '12px' }}>
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'var(--font-ui)', whiteSpace: 'nowrap' }}>
                {(t as any)('chat_input_hint')}
              </div>
              <div style={{ fontSize: '12px', color: hasFailed ? 'var(--error)' : hasUploading ? 'var(--accent)' : 'transparent', fontFamily: 'var(--font-mono)', flexShrink: 0, textAlign: 'right' }}>
                {composerStatusText}
              </div>
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
