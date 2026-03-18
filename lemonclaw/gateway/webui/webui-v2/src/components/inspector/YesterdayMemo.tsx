import { useEffect, useRef, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';
import { loadMemory, memory } from '../../stores/memory';

const COLLAPSED_MAX_HEIGHT = 220;
const HISTORY_COLLAPSED_MAX_HEIGHT = 180;

const shellStyle = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, var(--bg-secondary) 100%)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '14px',
  boxShadow: '0 12px 26px rgba(0,0,0,0.14)',
} as const;

function pillStyle(active = false) {
  return {
    padding: '4px 8px',
    borderRadius: '999px',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border)',
    background: active ? 'rgba(255, 107, 53, 0.08)' : 'var(--bg-primary)',
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    cursor: 'pointer',
  } as const;
}

export function YesterdayMemo() {
  const [memo, setMemo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [historySectionOpen, setHistorySectionOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [historyOverflows, setHistoryOverflows] = useState(false);

  useEffect(() => {
    void loadMemory();
    apiFetch('/api/memo/yesterday')
      .then((res) => res.json())
      .then((data) => {
        setMemo(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const hasMemoContent = Boolean(memo && (memo.yesterday?.length || memo.today?.length));
  const historyEntries = memory.value?.history || [];
  const hasAnyContent = hasMemoContent || historyEntries.length > 0;

  useEffect(() => {
    if (historyEntries.length > 0) {
      setHistorySectionOpen((open) => open || true);
    }
  }, [historyEntries.length]);

  useEffect(() => {
    if (!contentRef.current || !hasAnyContent) return;
    setOverflows(contentRef.current.scrollHeight > COLLAPSED_MAX_HEIGHT);
  }, [hasAnyContent, memo, historyEntries.length, historySectionOpen, historyExpanded]);

  useEffect(() => {
    if (!historyRef.current || historyEntries.length === 0) return;
    setHistoryOverflows(historyRef.current.scrollHeight > HISTORY_COLLAPSED_MAX_HEIGHT);
  }, [historyEntries.join('|')]);

  if (loading) return null;

  const handleExpandToggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && historyEntries.length > 0) {
      setHistorySectionOpen(true);
    }
  };

  const openHistory = () => {
    setExpanded(true);
    setHistorySectionOpen(true);
    setHistoryExpanded(true);
  };

  const toggleHistoryExpanded = () => {
    setExpanded(true);
    setHistorySectionOpen(true);
    setHistoryExpanded((value) => !value);
  };

  return (
    <div style={shellStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '10px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '8px' }}>
            // {t('memo_title')}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
            <button onClick={() => setExpanded(true)} style={pillStyle(Boolean(memo?.today?.length))}>{`${t('memo_today')}: ${memo?.today?.length || 0}`}</button>
            <button onClick={() => setExpanded(true)} style={pillStyle(Boolean(memo?.yesterday?.length))}>{`${t('memo_yesterday')}: ${memo?.yesterday?.length || 0}`}</button>
            <button onClick={openHistory} style={pillStyle(Boolean(historyEntries.length))}>{`${t('memo_history')}: ${historyEntries.length}`}</button>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' }}>{memo?.date || '—'}</span>
          <button onClick={handleExpandToggle} style={pillStyle(expanded)}>
            {expanded ? t('memo_collapse') : t('memo_expand')}
          </button>
        </div>
      </div>

      <div
        ref={contentRef}
        style={{
          maxHeight: expanded ? 'none' : `${COLLAPSED_MAX_HEIGHT}px`,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {!hasAnyContent ? (
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>{t('memo_empty')}</div>
        ) : (
          <div style={{ display: 'grid', gap: '12px' }}>
            {memo?.today?.length ? (
              <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '6px', fontWeight: 'bold' }}>{t('memo_today')}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
                  {memo.today.map((item: string, index: number) => (
                    <div key={`today-${index}`} style={{ marginBottom: index < memo.today.length - 1 ? '8px' : '0', paddingLeft: '8px', borderLeft: '2px solid var(--accent)' }}>
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {memo?.yesterday?.length ? (
              <details open>
                <summary style={{ cursor: 'pointer', fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                  {t('memo_yesterday')}
                </summary>
                <div style={{ marginTop: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
                  {memo.yesterday.map((item: string, index: number) => (
                    <div key={`yesterday-${index}`} style={{ marginBottom: index < memo.yesterday.length - 1 ? '8px' : '0', paddingLeft: '8px', borderLeft: '2px solid var(--border)' }}>
                      {item}
                    </div>
                  ))}
                </div>
              </details>
            ) : null}

            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', padding: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: historySectionOpen ? '8px' : '0' }}>
                <button
                  onClick={() => setHistorySectionOpen((open) => !open)}
                  style={{ ...pillStyle(historySectionOpen), fontSize: '10px' }}
                >
                  {`${t('memo_history')} · ${historyEntries.length}`}
                </button>
                {historyEntries.length > 0 ? (
                  <button onClick={toggleHistoryExpanded} style={pillStyle(historyExpanded)}>
                    {historyExpanded ? t('memo_collapse') : t('memo_expand')}
                  </button>
                ) : null}
              </div>
              {historySectionOpen ? (
                <div>
                {historyEntries.length === 0 ? (
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{t('memory_empty_history')}</div>
                ) : (
                  <>
                    <div
                      ref={historyRef}
                      style={{
                        maxHeight: historyExpanded ? 'none' : `${HISTORY_COLLAPSED_MAX_HEIGHT}px`,
                        overflow: 'hidden',
                      }}
                    >
                      <div style={{ display: 'grid', gap: '8px' }}>
                        {historyEntries.map((entry, index) => (
                          <div key={`memo-history-${index}`} style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
                            {entry}
                          </div>
                        ))}
                      </div>
                    </div>
                    {historyOverflows ? (
                      <button onClick={() => setHistoryExpanded((value) => !value)} style={{ ...pillStyle(historyExpanded), marginTop: '10px' }}>
                        {historyExpanded ? t('memo_collapse') : t('memo_expand')}
                      </button>
                    ) : null}
                  </>
                )}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>

      {hasAnyContent && overflows ? (
        <div style={{ position: 'relative' }}>
          {!expanded ? (
            <div
              style={{
                position: 'absolute',
                bottom: '100%',
                left: 0,
                right: 0,
                height: '48px',
                background: 'linear-gradient(to bottom, transparent, var(--bg-secondary))',
                pointerEvents: 'none',
              }}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
