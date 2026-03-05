import { useEffect, useState } from 'preact/hooks';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

export function YesterdayMemo() {
  const [memo, setMemo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch('/api/memo/yesterday')
      .then(res => res.json())
      .then(data => { setMemo(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (!memo || (!memo.yesterday?.length && !memo.today)) return null;

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '12px', marginBottom: '16px' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
        <span>// MEMO</span>
        <span>{memo.date}</span>
      </div>
      
      {memo.yesterday && memo.yesterday.length > 0 && (
        <div style={{ marginBottom: memo.today ? '12px' : '0' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_yesterday')}</div>
          <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '11px', color: 'var(--text-primary)' }}>
            {memo.yesterday.map((item: string, i: number) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      )}
      
      {memo.today && (
        <div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 'bold' }}>{t('memo_today')}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>{memo.today}</div>
        </div>
      )}
    </div>
  );
}