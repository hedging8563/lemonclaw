import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

const COLLAPSED_MAX_HEIGHT = 320;

export function YesterdayMemo() {
  const [memo, setMemo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    apiFetch('/api/memo/yesterday')
      .then((res) => res.json())
      .then((data) => {
        setMemo(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const hasContent = Boolean(memo && (memo.yesterday?.length || memo.today?.length));

  // Measure actual content height to decide if toggle is needed
  useEffect(() => {
    if (!contentRef.current || !hasContent) return;
    const el = contentRef.current;
    setOverflows(el.scrollHeight > COLLAPSED_MAX_HEIGHT);
  }, [hasContent, memo]);

  if (loading) return null;
  if (!hasContent) return null;

  const showToggle = overflows;

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', marginBottom: '16px' }}>
      {/* Header */}
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>// MEMO</span>
        <span>{memo.date}</span>
      </div>

      {/* Content */}
      <div
        ref={contentRef}
        style={{
          maxHeight: expanded ? 'none' : `${COLLAPSED_MAX_HEIGHT}px`,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {memo.yesterday && memo.yesterday.length > 0 && (
          <div style={{ marginBottom: memo.today?.length ? '12px' : '0' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_yesterday')}</div>
            <div style={{ fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
              {memo.yesterday.map((item: string, i: number) => (
                <div key={i} style={{ marginBottom: i < memo.yesterday.length - 1 ? '8px' : '0', paddingLeft: '8px', borderLeft: '2px solid var(--border)' }}>{item}</div>
              ))}
            </div>
          </div>
        )}

        {memo.today && memo.today.length > 0 && (
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_today')}</div>
            <div style={{ fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
              {memo.today.map((item: string, i: number) => (
                <div key={i} style={{ marginBottom: i < memo.today.length - 1 ? '8px' : '0', paddingLeft: '8px', borderLeft: '2px solid var(--accent)' }}>{item}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Fade overlay + bottom toggle */}
      {showToggle && (
        <div style={{ position: 'relative' }}>
          {!expanded && (
            <div style={{
              position: 'absolute',
              bottom: '100%',
              left: 0,
              right: 0,
              height: '48px',
              background: 'linear-gradient(to bottom, transparent, var(--bg-secondary))',
              pointerEvents: 'none',
            }} />
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              width: '100%',
              marginTop: '8px',
              padding: '4px 0',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              transition: 'color 0.15s, border-color 0.15s',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--accent)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--accent)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)';
            }}
          >
            <span style={{ fontSize: '8px' }}>{expanded ? '▲' : '▼'}</span>
            <span>{expanded ? t('memo_collapse') : t('memo_expand')}</span>
          </button>
        </div>
      )}
    </div>
  );
}
