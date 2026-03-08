import { useState } from 'preact/hooks';
import { t } from '../../stores/i18n';
import { normalizeMessage } from '../../models/messages';
import type { UIBlock, UIMedia } from '../../models/messages';

function isPreviewableImage(media: UIMedia): boolean {
  return media.kind === 'image';
}

function isPlayableAudio(media: UIMedia): boolean {
  return media.kind === 'audio' || media.kind === 'voice';
}

function isPlayableVideo(media: UIMedia): boolean {
  return media.kind === 'video';
}

function isPreviewablePdf(media: UIMedia): boolean {
  return media.kind === 'pdf';
}

export function RuntimeContextCard({ content }: { content: string }) {
  return (
    <details style={{ margin: '0 0 8px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-secondary)' }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '8px 10px', fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        Runtime Context
      </summary>
      <div style={{ padding: '0 10px 10px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px', lineHeight: 1.6, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
        {content}
      </div>
    </details>
  );
}

export function MediaMarkerCard({ media }: { media: UIMedia }) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const iconMap: Record<string, string> = { image: '🖼️', audio: '🎵', voice: '🎤', video: '🎬', pdf: '📕', file: '📎', document: '📄' };
  const toneMap: Record<string, { bg: string; color: string; border: string }> = {
    image: { bg: 'rgba(100,149,237,0.12)', color: 'cornflowerblue', border: 'rgba(100,149,237,0.28)' },
    audio: { bg: 'rgba(20,184,166,0.12)', color: 'var(--teal)', border: 'rgba(20,184,166,0.28)' },
    voice: { bg: 'rgba(168,85,247,0.12)', color: 'var(--purple)', border: 'rgba(168,85,247,0.28)' },
    video: { bg: 'rgba(255,107,53,0.12)', color: 'var(--accent)', border: 'rgba(255,107,53,0.28)' },
    pdf: { bg: 'rgba(255,68,68,0.12)', color: 'var(--error)', border: 'rgba(255,68,68,0.28)' },
    file: { bg: 'rgba(148,163,184,0.12)', color: 'var(--text-secondary)', border: 'rgba(148,163,184,0.28)' },
    document: { bg: 'rgba(148,163,184,0.12)', color: 'var(--text-secondary)', border: 'rgba(148,163,184,0.28)' },
  };
  const url = media.url;
  const tone = toneMap[media.kind] || toneMap.file;
  const canPreviewImage = isPreviewableImage(media);
  const canPlayAudio = isPlayableAudio(media);
  const canPlayVideo = isPlayableVideo(media);
  const canPreviewPdf = isPreviewablePdf(media);

  return (
    <>
      <div style={{ margin: '8px 0', border: '1px solid var(--border)', borderRadius: '8px', background: 'linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-primary) 100%)', padding: '12px 14px', boxShadow: '0 6px 18px rgba(0,0,0,0.16)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '3px 8px', borderRadius: '999px', background: tone.bg, color: tone.color, border: `1px solid ${tone.border}`, fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.04em' }}>
            <span>{iconMap[media.kind] || '📎'}</span>
            <span>{media.kind.toUpperCase()}</span>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '10px', color: 'var(--accent)', textDecoration: 'none', fontFamily: 'var(--font-mono)', padding: '3px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)' }}>
              {t('open')}
            </a>
            <a href={url} download={media.filename || 'file'} style={{ fontSize: '10px', color: 'var(--teal)', textDecoration: 'none', fontFamily: 'var(--font-mono)', padding: '3px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-primary)' }}>
              {t('download')}
            </a>
          </div>
        </div>
        {media.filename && <div style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '8px', wordBreak: 'break-word', fontWeight: 600 }}>{media.filename}</div>}
        {canPreviewImage && (
          <button type="button" onClick={() => setLightboxOpen(true)} style={{ display: 'block', marginBottom: '8px', width: '100%', padding: 0, border: 'none', background: 'transparent', cursor: 'zoom-in' }} aria-label="Open image preview">
            <img src={url} alt={media.filename || media.path} style={{ display: 'block', width: '100%', maxHeight: '240px', objectFit: 'contain', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-primary)' }} loading="lazy" />
          </button>
        )}
        {canPlayAudio && (
          <audio controls preload="none" src={url} style={{ display: 'block', width: '100%', marginBottom: '8px' }} />
        )}
        {canPlayVideo && (
          <video controls preload="metadata" src={url} style={{ display: 'block', width: '100%', maxHeight: '320px', marginBottom: '8px', borderRadius: '6px', background: '#000' }} />
        )}
        {canPreviewPdf && (
          <iframe title={media.filename || media.path} src={url} style={{ display: 'block', width: '100%', height: '360px', marginBottom: '8px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-primary)' }} />
        )}
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', wordBreak: 'break-all' }}>{media.path}</div>
      </div>
      {lightboxOpen && canPreviewImage && (
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.82)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }} onClick={() => setLightboxOpen(false)}>
          <div style={{ position: 'relative', maxWidth: 'min(92vw, 1200px)', maxHeight: '90vh', width: '100%' }} onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setLightboxOpen(false)} style={{ position: 'absolute', top: '-12px', right: '-12px', width: '36px', height: '36px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '20px', lineHeight: 1 }}>×</button>
            <img src={url} alt={media.filename || media.path} style={{ display: 'block', width: '100%', maxHeight: '90vh', objectFit: 'contain', borderRadius: '8px', background: '#000' }} />
          </div>
        </div>
      )}
    </>
  );
}

export function SystemNoticeCard({ text, level = 'info' }: { text: string; level?: 'info' | 'warning' | 'error' }) {
  const icon = level === 'error' ? '⛔' : level === 'warning' ? '⚠️' : 'ℹ️';
  const title = level === 'error' ? 'ERROR' : level === 'warning' ? 'NOTICE' : 'SYSTEM';
  const border = level === 'error' ? 'rgba(255, 68, 68, 0.28)' : level === 'warning' ? 'rgba(255, 170, 0, 0.28)' : 'rgba(100, 149, 237, 0.28)';
  const bg = level === 'error' ? 'rgba(255, 68, 68, 0.08)' : level === 'warning' ? 'rgba(255, 170, 0, 0.08)' : 'rgba(100, 149, 237, 0.08)';
  const color = level === 'error' ? 'var(--error)' : level === 'warning' ? 'var(--warning, #ffb84d)' : 'var(--text-secondary)';
  return (
    <div style={{ margin: '8px 0', border: `1px solid ${border}`, borderRadius: '8px', background: bg, color, padding: '10px 12px', boxShadow: '0 4px 12px rgba(0,0,0,0.12)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.06em' }}>
        <span>{icon}</span><span>{title}</span>
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{text}</div>
    </div>
  );
}

export function TranscriptionCard({ content }: { content: string }) {
  return (
    <div style={{ margin: '6px 0', borderLeft: '3px solid var(--teal)', borderRadius: '4px', background: 'var(--bg-secondary)', padding: '8px 12px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--teal)', marginBottom: '4px' }}>
        TRANSCRIPTION
      </div>
      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12px', lineHeight: 1.7, color: 'var(--text-primary)' }}>{content}</div>
    </div>
  );
}

export function StructuredMessageContent({
  content,
  media = [],
  blocks,
  renderMarkdown,
}: {
  content: string;
  media?: UIMedia[] | string[];
  blocks?: UIBlock[];
  renderMarkdown: (content: string) => string;
}) {
  const normalized = blocks ? { blocks, media: (media as UIMedia[]) } : normalizeMessage({ role: 'assistant', content, media });
  const renderBlocks = normalized.blocks;
  const mediaMap = new Map(normalized.media.map((m) => [m.id, m] as const));
  const hasStructured = renderBlocks.some((part) => part.type !== 'markdown');

  if (!hasStructured) {
    return (
      <div
        className="msg-content markdown-body"
        style={{ wordBreak: 'break-word', textAlign: 'left' }}
        dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {renderBlocks.map((part, pi) => {
        if (part.type === 'markdown') {
          return (
            <div
              key={pi}
              className="msg-content markdown-body"
              style={{ wordBreak: 'break-word', textAlign: 'left' }}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(part.text) }}
            />
          );
        }
        if (part.type === 'runtime_context') {
          return <RuntimeContextCard key={pi} content={part.text} />;
        }
        if (part.type === 'system_notice') {
          return <SystemNoticeCard key={pi} text={part.text} level={part.level} />;
        }
        if (part.type === 'transcription') {
          return <TranscriptionCard key={pi} content={part.text} />;
        }
        if (part.type === 'media') {
          const mediaItem = mediaMap.get(part.mediaId);
          return mediaItem ? <MediaMarkerCard key={pi} media={mediaItem} /> : null;
        }
        return null;
      })}
    </div>
  );
}
