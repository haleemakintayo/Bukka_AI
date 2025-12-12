import React, { useState } from 'react';
import { Send } from 'lucide-react';

const ChatInput = ({ onSend, isSending }) => {
  const [input, setInput] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isSending) {
      onSend(input);
      setInput('');
    }
  };

  return (
    <div className="bg-[#f0f2f5] px-4 py-2 flex items-center gap-2 shrink-0 z-20">
      <form onSubmit={handleSubmit} className="flex-1 flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message"
          className="flex-1 py-2 px-4 rounded-lg border-none focus:ring-0 focus:outline-none bg-white text-gray-700 placeholder-gray-500 shadow-sm"
          disabled={isSending}
        />
        <button 
          type="submit" 
          disabled={!input.trim() || isSending}
          className={`p-2 rounded-full transition-all duration-200 flex items-center justify-center transform
            ${input.trim() && !isSending 
              ? 'bg-[#008069] text-white hover:bg-[#006d59] scale-100' 
              : 'text-gray-400 bg-transparent scale-95'}`}
        >
          <Send size={20} />
        </button>
      </form>
    </div>
  );
};

export default ChatInput;