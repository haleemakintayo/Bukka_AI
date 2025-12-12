import { useState, useEffect, useCallback } from 'react';
import { fetchMessages, sendToWebhook, resetDemo } from '../services/api';
import { POLL_INTERVAL } from '../utils/constants';

export const useChat = (activePersona) => {
  const [messages, setMessages] = useState([]);
  const [isSending, setIsSending] = useState(false);

  const refreshMessages = useCallback(async () => {
    try {
      const data = await fetchMessages();
      if (Array.isArray(data)) setMessages(data);
    } catch (err) {
      console.error("Polling error", err);
    }
  }, []);

  useEffect(() => {
    refreshMessages();
    const interval = setInterval(refreshMessages, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [refreshMessages]);

  const sendMessage = async (text) => {
    if (!text.trim()) return;
    setIsSending(true);
    try {
      await sendToWebhook(text, activePersona.phone);
      await refreshMessages();
    } catch (err) {
      alert("Failed to send");
    } finally {
      setIsSending(false);
    }
  };

  const clearChat = async () => {
    if (confirm("Clear history?")) {
      await resetDemo();
      setMessages([]);
    }
  };

  return { messages, sendMessage, clearChat, isSending };
};