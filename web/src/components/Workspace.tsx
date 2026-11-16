import React, { useState } from 'react';
import { ChatScreen, type ChatMessage } from './ChatScreen';
import { VaultManager } from './VaultManager';

/** Chat is the default screen after unlock; Vault Manager is for CRUD / import / backup. */
export const Workspace: React.FC<{ demo: boolean; onLock: () => void }> = ({ demo, onLock }) => {
  const [view, setView] = useState<'chat' | 'manager'>('chat');
  // Transcript is RAM-only and dies with this component (i.e. on lock); never persisted.
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  return view === 'chat' ? (
    <ChatScreen demo={demo} messages={messages} setMessages={setMessages} onLock={onLock} onManage={() => setView('manager')} />
  ) : (
    <VaultManager demo={demo} onLock={onLock} onChat={() => setView('chat')} />
  );
};
