import axios from 'axios';
import { API_BASE } from '../utils/constants';

const api = axios.create({ baseURL: API_BASE });

export const fetchMessages = async () => {
  const response = await api.get('/demo/chats');
  return response.data;
};

export const resetDemo = async () => {
  return await api.post('/demo/reset');
};

export const sendToWebhook = async (text, senderPhone) => {
  const payload = {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "SIMULATOR_ID",
        changes: [
          {
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: senderPhone,
                phone_number_id: "SIMULATOR_PHONE_ID"
              },
              contacts: [{ profile: { name: "Simulator User" }, wa_id: senderPhone }],
              messages: [
                {
                  from: senderPhone,
                  id: `wamid.SIMULATOR_${Date.now()}`,
                  timestamp: Math.floor(Date.now() / 1000),
                  text: { body: text },
                  type: "text"
                }
              ]
            },
            field: "messages"
          }
        ]
      }
    ]
  };
  return await api.post('/webhook', payload);
};