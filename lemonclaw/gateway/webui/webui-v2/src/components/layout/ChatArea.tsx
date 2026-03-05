import { MessageList } from '../chat/MessageList';
import { MessageInput } from '../chat/MessageInput';
import { TopBar } from './TopBar';

export function ChatArea() {
  return (
    <main class="layout-main">
      <TopBar />
      <MessageList />
      <MessageInput />
    </main>
  );
}