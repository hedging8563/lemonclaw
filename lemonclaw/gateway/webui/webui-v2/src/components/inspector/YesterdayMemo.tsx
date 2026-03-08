import { useEffect, useMemo, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

const PREVIEW_LINE_THRESHOLD = 20;
const PREVIEW_MAX_HEIGHT = 360;
const EXPANDED_MAX_HEIGHT = 420;

export function YesterdayMemo() {
  const [memo, setMemo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    apiFetch('/api/memo/yesterday')
      .then((res) => res.json())
      .then((data) => {
        setMemo(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const hasContent = Boolean(memo && (memo.yesterday?.length || memo.today));
  const contentLineEstimate = useMemo(() => {
    if (!hasContent) return 0;
    const yesterdayLines = Array.isArray(memo.yesterday)
      ? memo.yesterday.reduce(
          (sum: number, item: string) => sum + Math.max(String(item || '').split('\n').length, 1),
          0,
        )
      : 0;
    const todayLines = memo.today ? String(memo.today).split('\n').length : 0;
    return yesterdayLines + todayLines;
  }, [hasContent, memo]);

  if (loading) return null;
  if (!hasContent) return null;

  const showToggle = contentLineEstimate > PREVIEW_LINE_THRESHOLD;
  const contentStyle = {
    maxHeight: expanded ? `${EXPANDED_MAX_HEIGHT}px` : `${PREVIEW_MAX_HEIGHT}px`,
    overflowY: expanded ? 'auto' : 'hidden',
    overflowX: 'hidden',
    paddingRight: expanded ? '4px' : '0',
    maskImage: !expanded && showToggle ? 'linear-gradient(to bottom, black 84%, transparent 100%)' : 'none',
    WebkitMaskImage: !expanded && showToggle ? 'linear-gradient(to bottom, black 84%, transparent 100%)' : 'none',
  } as const;

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', marginBottom: '16px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
        <span>// MEMO</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>{memo.date}</span>
          {showToggle && (
            <button
              onClick={() => setExpanded((value) => !value)}
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: '999px',
                color: expanded ? 'var(--accent)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                padding: '2px 8px',
                lineHeight: 1.4,
              }}
            >
              {expanded ? t('memo_collapse') : t('memo_expand')}
            </button>
          )}
        </div>
      </div>

      <div style={contentStyle}>
        {memo.yesterday && memo.yesterday.length > 0 && (
          <div style={{ marginBottom: memo.today ? '12px' : '0' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_yesterday')}</div>
            <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55 }}>
              {memo.yesterday.map((item: string, i: number) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        )}

        {memo.today && (
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_today')}</div>
            <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{memo.today}</div>
          </div>
        )}
      </div>
    </div>
  );
}
