import React, { useState } from 'react';
import ControlPanel from '../components/ControlPanel';
import ChatWindow from '../components/ChatWindow';
import { useChat } from '../hooks/useChat';
import { PERSONAS } from '../utils/constants';

function App() {
  const [activePersona, setActivePersona] = useState(PERSONAS.STUDENT);
  const { messages, sendMessage, clearChat, isSending } = useChat(activePersona);

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col items-center justify-center p-4 font-sans">
      <ControlPanel 
        activePersona={activePersona} 
        setActivePersona={setActivePersona} 
        onReset={clearChat}
      />
      <ChatWindow 
        activePersona={activePersona} 
        messages={messages} 
        onSend={sendMessage}
        isSending={isSending}
      />
      <p className="mt-4 text-xs text-gray-400">Demo Controller • Bukka AI</p>
    </div>
  );
}

export default App;