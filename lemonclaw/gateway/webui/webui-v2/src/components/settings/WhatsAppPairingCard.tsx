import { useEffect, useRef, useState } from 'preact/hooks';
import QRCode from 'qrcode';
import { apiFetch } from '../../api/client';
import { t } from '../../stores/i18n';

const MAX_POLL_ATTEMPTS = 30;

type PairingAccount = {
  id?: string;
  phone?: string;
  name?: string;
};

type PairingResponse = {
  status?: string;
  running?: boolean;
  qr?: string | null;
  error?: string | null;
  account?: PairingAccount | null;
};

export function WhatsAppPairingCard({ enabled, dirty }: { enabled: boolean; dirty: boolean }) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>('idle');
  const [error, setError] = useState<string | null>(null);
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [account, setAccount] = useState<PairingAccount | null>(null);
  const pollRef = useRef<number | null>(null);
  const pollAttemptsRef = useRef(0);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => {
    if (enabled && !dirty) {
      void fetchState(false);
    }
    return () => stopPolling();
  }, [enabled, dirty]);

  const applyState = async (data: PairingResponse) => {
    const nextStatus = data.status || 'unknown';
    setStatus(nextStatus);
    setError(data.error || null);
    setAccount((data.account as PairingAccount | null) || null);
    if (typeof data.qr === 'string' && data.qr.trim()) {
      const image = await QRCode.toDataURL(data.qr, { width: 256, margin: 1 });
      setQrImage(image);
    } else if (nextStatus === 'connected' || nextStatus === 'disconnected') {
      setQrImage(null);
    }
    if (nextStatus === 'connected' || nextStatus === 'error' || nextStatus === 'disabled' || nextStatus === 'disconnected') {
      stopPolling();
    }
  };

  const fetchState = async (start: boolean) => {
    setLoading(start);
    setError(null);
    try {
      const res = await apiFetch('/api/settings/channels/whatsapp/pairing', {
        method: start ? 'POST' : 'GET',
      });
      const data = await res.json();
      await applyState(data);
      if (start && data.status !== 'connected' && pollRef.current === null) {
        pollAttemptsRef.current = 0;
        pollRef.current = window.setInterval(() => {
          pollAttemptsRef.current += 1;
          if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
            stopPolling();
            setError(t('whatsapp_pairing_poll_timeout'));
            return;
          }
          fetchState(false).catch((e) => console.error('whatsapp pairing poll failed', e));
        }, 3000);
      }
    } catch (e: any) {
      setError(e?.message || 'Pairing request failed');
      stopPolling();
    } finally {
      setLoading(false);
    }
  };

  const callAction = async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(path, { method: 'POST' });
      const data = await res.json();
      await applyState(data);
      if (path.endsWith('/repair') && data.status !== 'connected' && pollRef.current === null) {
        pollAttemptsRef.current = 0;
        pollRef.current = window.setInterval(() => {
          pollAttemptsRef.current += 1;
          if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
            stopPolling();
            setError(t('whatsapp_pairing_poll_timeout'));
            return;
          }
          fetchState(false).catch((e) => console.error('whatsapp pairing poll failed', e));
        }, 3000);
      }
    } catch (e: any) {
      setError(e?.message || 'Action failed');
      stopPolling();
    } finally {
      setLoading(false);
    }
  };

  const disabledReason = dirty
    ? t('whatsapp_pairing_save_first')
    : !enabled
      ? t('whatsapp_pairing_disabled')
      : null;

  const summary = account
    ? [account.name, account.phone, account.id].filter(Boolean).join(' · ')
    : null;

  return (
    <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px dashed var(--border)' }}>
      <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: '6px' }}>
        {t('whatsapp_pairing_title')}
      </div>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: '10px' }}>
        {t('whatsapp_pairing_desc')}
      </div>

      {summary && (
        <div style={{ marginBottom: '10px', padding: '10px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '11px', lineHeight: 1.6 }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('whatsapp_pairing_account')}</div>
          <div>{summary}</div>
        </div>
      )}

      {status === 'connected' && (
        <div style={{ marginBottom: '10px', padding: '10px 12px', borderRadius: '6px', border: '1px solid rgba(76, 175, 80, 0.28)', background: 'rgba(76, 175, 80, 0.08)', color: 'var(--success)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
          {t('whatsapp_pairing_connected')}
        </div>
      )}

      {status !== 'connected' && qrImage && (
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px' }}>
          <img src={qrImage} alt={t('whatsapp_pairing_qr_alt')} style={{ width: '256px', height: '256px', borderRadius: '8px', background: '#fff', padding: '8px' }} />
        </div>
      )}

      {error && (
        <div style={{ marginBottom: '10px', padding: '10px 12px', borderRadius: '6px', border: '1px solid rgba(255, 68, 68, 0.28)', background: 'rgba(255, 68, 68, 0.08)', color: 'var(--error)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
          {error}
        </div>
      )}

      {!error && status !== 'connected' && status !== 'idle' && status !== 'qr' && status !== 'disconnected' && (
        <div style={{ marginBottom: '10px', fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {status === 'starting' ? t('whatsapp_pairing_loading') : t('whatsapp_pairing_waiting')}
        </div>
      )}

      {disabledReason && (
        <div style={{ marginBottom: '10px', fontSize: '11px', color: 'var(--warning, #ffb84d)', fontFamily: 'var(--font-mono)' }}>
          {disabledReason}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <button
          onClick={() => fetchState(true)}
          disabled={Boolean(disabledReason) || loading}
          style={{
            padding: '8px 12px',
            background: Boolean(disabledReason) || loading ? 'var(--bg-tertiary)' : 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: Boolean(disabledReason) || loading ? 'not-allowed' : 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
          }}
        >
          {loading ? t('whatsapp_pairing_loading') : (qrImage ? t('whatsapp_pairing_refresh') : t('whatsapp_pairing_start'))}
        </button>

        <button
          onClick={() => callAction('/api/settings/channels/whatsapp/disconnect')}
          disabled={Boolean(disabledReason) || loading || status !== 'connected'}
          style={{
            padding: '8px 12px',
            background: Boolean(disabledReason) || loading || status !== 'connected' ? 'var(--bg-tertiary)' : 'transparent',
            color: status === 'connected' ? 'var(--text-primary)' : 'var(--text-muted)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            cursor: Boolean(disabledReason) || loading || status !== 'connected' ? 'not-allowed' : 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
          }}
        >
          {t('whatsapp_pairing_disconnect')}
        </button>

        <button
          onClick={() => callAction('/api/settings/channels/whatsapp/repair')}
          disabled={Boolean(disabledReason) || loading}
          style={{
            padding: '8px 12px',
            background: Boolean(disabledReason) || loading ? 'var(--bg-tertiary)' : 'transparent',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            cursor: Boolean(disabledReason) || loading ? 'not-allowed' : 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
          }}
        >
          {t('whatsapp_pairing_repair')}
        </button>
      </div>
    </div>
  );
}
