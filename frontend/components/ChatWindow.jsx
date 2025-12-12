import React, { useEffect, useRef } from 'react';
import { ArrowLeft, MoreVertical, Phone, User } from 'lucide-react';
import ChatInput from './ChatInput';

const ChatWindow = ({ activePersona, messages, onSend, isSending }) => {
  const messagesEndRef = useRef(null);

  const relevantMessages = messages.filter(msg => 
    msg.from === activePersona.phone || msg.to === activePersona.phone
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activePersona]);

  // Format time helper
  const formatTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    // MAIN CONTAINER: Fixed height, centered, flex column
    <div className="flex flex-col w-full max-w-md h-[600px] bg-[#efeae2] border rounded-b-xl shadow-xl mx-auto overflow-hidden relative">
      
      {/* HEADER: Fixed height, green background */}
      <div className="bg-[#008069] text-white px-4 py-3 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          <ArrowLeft size={24} className="cursor-pointer" />
          <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-gray-500">
             <User size={24} />
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-base">{activePersona.contactName}</span>
            <span className="text-xs text-green-100 opacity-90">Online</span>
          </div>
        </div>
        <div className="flex gap-5">
            <Phone size={20} />
            <MoreVertical size={20} />
        </div>
      </div>

      {/* CHAT AREA: Grows to fill space, scrolls vertically */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 relative" 
           style={{ backgroundImage: "url('https://user-images.githubusercontent.com/15075759/28719144-86dc0f70-73b1-11e7-911d-60d70fcded21.png')", backgroundSize: '400px' }}>
        
        {relevantMessages.length === 0 && (
            <div className="text-center text-xs text-gray-500 bg-[#e1f3fb] p-2 rounded-lg my-4 shadow-sm mx-auto w-fit">
                Messages are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
            </div>
        )}

        {relevantMessages.map((msg, idx) => {
          const isMe = msg.from === activePersona.phone;
          return (
            <div key={idx} className={`flex w-full ${isMe ? 'justify-end' : 'justify-start'}`}>
              <div 
                className={`relative max-w-[80%] px-3 py-2 rounded-lg shadow-sm text-sm leading-relaxed
                ${isMe ? 'bg-[#d9fdd3] text-gray-800 rounded-tr-none' : 'bg-white text-gray-800 rounded-tl-none'}`}
              >
                {/* Message Body */}
                <p className="mr-2 mb-1">{msg.body || msg.text?.body}</p>
                
                {/* Timestamp */}
                <span className="text-[10px] text-gray-500 float-right mt-1 ml-2 block">
                    {formatTime(msg.timestamp)}
                </span>
              </div>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* FOOTER: Fixed at bottom */}
      <div className="shrink-0 bg-[#f0f2f5]">
          <ChatInput onSend={onSend} isSending={isSending} />
      </div>
    </div>
  );
};

export default ChatWindow;