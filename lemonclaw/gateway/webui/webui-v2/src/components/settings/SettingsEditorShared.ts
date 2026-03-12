export const MOBILE_BREAKPOINT = 640;

export const srOnly = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

export const editorStyles = {
  card: { marginBottom: '12px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '6px', overflow: 'hidden' } as const,
  headerRow: { display: 'flex', alignItems: 'stretch', justifyContent: 'space-between', gap: '8px' } as const,
  headerButton: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '12px 16px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' as const } as const,
  cardBody: { padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: '10px' } as const,
  label: { display: 'block', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px', fontFamily: 'var(--font-mono)' } as const,
  input: { width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', boxSizing: 'border-box' } as const,
  textarea: { width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '8px 10px', borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '12px', outline: 'none', resize: 'vertical', minHeight: '60px', boxSizing: 'border-box' } as const,
  tag: (color: 'green' | 'blue') => ({ fontSize: '10px', padding: '2px 6px', borderRadius: '3px', fontFamily: 'var(--font-mono)', background: color === 'green' ? 'rgba(76,175,80,0.15)' : 'rgba(100,149,237,0.15)', color: color === 'green' ? 'var(--success)' : 'cornflowerblue', border: `1px solid ${color === 'green' ? 'rgba(76,175,80,0.3)' : 'rgba(100,149,237,0.3)'}` }),
  deleteBtn: { alignSelf: 'center', background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', fontSize: '16px', padding: '4px 8px', borderRadius: '4px', lineHeight: 1 } as const,
  addBtn: { width: '100%', padding: '10px', background: 'var(--bg-secondary)', border: '1px dashed var(--border)', borderRadius: '6px', color: 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px' } as const,
  row: { display: 'flex', gap: '10px' } as const,
  modeBtn: (active: boolean) => ({ flex: 1, padding: '6px', background: active ? 'var(--bg-tertiary)' : 'transparent', border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`, borderRadius: '4px', color: active ? 'var(--accent)' : 'var(--text-muted)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px' }),
  notice: (warning: boolean) => ({ marginBottom: '12px', padding: '10px 12px', borderRadius: '6px', border: `1px solid ${warning ? 'rgba(255, 170, 0, 0.28)' : 'rgba(100, 149, 237, 0.28)'}`, background: warning ? 'rgba(255, 170, 0, 0.08)' : 'rgba(100, 149, 237, 0.08)', color: warning ? 'var(--warning, #ffb84d)' : 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '11px', lineHeight: 1.6 }) as const,
} as const;

export function dictToLines(d: Record<string, string> | undefined): string {
  if (!d) return '';
  return Object.entries(d).map(([k, v]) => `${k}=${v}`).join('\n');
}

export function linesToDict(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const idx = trimmed.indexOf('=');
    if (idx > 0) {
      result[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
  }
  return result;
}
