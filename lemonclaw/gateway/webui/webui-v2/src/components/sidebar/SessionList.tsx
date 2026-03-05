import { useEffect } from 'preact/hooks';
import { sessions, loadSessions } from '../../stores/sessions';
import { SessionItem } from './SessionItem';

export function SessionList() {
  useEffect(() => {
    loadSessions();
  }, []);

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
      {sessions.value.map(session => (
        <SessionItem key={session.key} session={session} />
      ))}
    </div>
  );
}