import { Component } from 'preact';
import { t } from '../stores/i18n';

interface State {
  error: Error | null;
}

function safeT(key: 'error_boundary' | 'error_retry', fallback: string): string {
  try { return t(key); } catch { return fallback; }
}

export class ErrorBoundary extends Component<{ children: any }, State> {
  state: State = { error: null };

  componentDidCatch(error: Error) {
    this.setState({ error });
    console.error('ErrorBoundary caught:', error);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', gap: '16px', background: 'var(--bg-primary)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
          <div style={{ fontSize: '14px', color: 'var(--error)' }}>{safeT('error_boundary', 'Something went wrong')}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', maxWidth: '400px', textAlign: 'center', wordBreak: 'break-word' }}>
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ padding: '8px 24px', background: 'var(--accent)', border: 'none', borderRadius: '6px', color: '#fff', cursor: 'pointer', fontSize: '12px', fontFamily: 'var(--font-mono)' }}
          >
            {safeT('error_retry', 'RETRY')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
