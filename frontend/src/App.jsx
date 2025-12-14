import React, { useEffect, useRef, useState } from "react";

const STUDENT = { id: "student", label: "Student", phone: "2347000000000" };
const OWNER = { id: "owner", label: "Owner", phone: "2348012345678" };
const API_BASE = "https://bukka-ai-backend-523632194f78.herokuapp.com";

export default function App() {
  const [persona, setPersona] = useState(STUDENT);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const endRef = useRef(null);

  const formatTime = (ts) =>
    new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const getTickStatus = (msg) => {
    if (msg.from !== persona.phone) return null;
    if (msg.id?.startsWith("local_")) return "sent";
    return "delivered";
  };

  const buildPayload = (text) => ({
    entry: [
      {
        changes: [
          {
            value: {
              messages: [
                {
                  from: persona.phone,
                  to: "BukkaAI",
                  id: `msg_${Date.now()}`,
                  timestamp: Math.floor(Date.now() / 1000).toString(),
                  type: "text",
                  text: { body: text },
                },
              ],
            },
          },
        ],
      },
    ],
  });

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/demo/chats`);
        const data = await res.json();
        setMessages((prev) => {
          const map = new Map(prev.map((m) => [m.id, m]));
          data.forEach((m) => {
            map.set(m.id ?? `${m.from}_${m.timestamp}`, {
              ...m,
              body: m.body ?? m.text?.body ?? "",
              timestamp: Number(m.timestamp),
            });
          });
          return Array.from(map.values()).sort((a, b) => a.timestamp - b.timestamp);
        });
      } catch {}
    };
    poll();
    const i = setInterval(poll, 2000);
    return () => clearInterval(i);
  }, []);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || isSending) return;
    const text = input.trim();
    setInput("");
    setIsSending(true);
    setMessages((prev) => [
      ...prev,
      { id: `local_${Date.now()}`, from: persona.phone, to: "BukkaAI", body: text, timestamp: Math.floor(Date.now() / 1000) },
    ]);
    try {
      await fetch(`${API_BASE}/webhook`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload(text)) });
    } finally { setIsSending(false); }
  };

  const resetDemo = async () => {
    await fetch(`${API_BASE}/demo/reset`, { method: "POST" });
    setMessages([]);
  };

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  return (
    <div className="relative min-h-screen flex flex-col items-center px-4 text-gray-200
                    bg-gradient-to-r from-[#0b141a] via-[#0f1c22] to-[#091114]
                    animate-gradient-x bg-[length:400%_400%]">

      {/* HEADER */}
      <header className="w-full max-w-3xl text-center py-4 mb-4">
        <h1 className="text-3xl font-bold text-white tracking-wide">Bukka AI</h1>
      </header>

      {/* MAIN CONTENT */}
      <div className="flex flex-col md:flex-row items-start md:items-stretch justify-center gap-5 w-full max-w-3xl">

        {/* CHAT CONTAINER */}
        <div className="w-full md:w-3/5 h-[500px] flex flex-col backdrop-blur-xl bg-white/5 border border-white/10 rounded-2xl shadow-xl overflow-hidden">

          {/* CHAT HEADER */}
          <div className="px-3 py-2 flex items-center justify-between bg-black/30 border-b border-white/10">
            <div className="flex gap-2">
              {[STUDENT, OWNER].map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPersona(p)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium transition
                    ${persona.id === p.id ? "bg-[#005c4b] text-white" : "text-gray-400 hover:text-gray-200"}`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <button onClick={resetDemo} className="text-xs text-gray-400 hover:text-red-400 transition">
              Reset
            </button>
          </div>

          {/* CHAT MESSAGES */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2 bg-[url('https://www.transparenttextures.com/patterns/dark-mosaic.png')]">
            {messages
              .filter((m) => m.from === persona.phone || m.to === persona.phone)
              .map((m) => {
                const isMe = m.from === persona.phone;
                const tick = getTickStatus(m);
                return (
                  <div key={m.id} className={`flex ${isMe ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[75%] px-3 py-2 text-sm rounded-xl shadow
                      ${isMe ? "bg-[#005c4b] text-white rounded-br-sm" : "bg-white/10 backdrop-blur-md text-gray-100 rounded-bl-sm"}`}>
                      <p className="leading-relaxed">{m.body}</p>
                      <div className="flex items-center justify-end gap-1 text-[10px] opacity-70 mt-1">
                        <span>{formatTime(m.timestamp)}</span>
                        {isMe && (
                          <span className={tick === "delivered" ? "text-[#53bdeb]" : "text-gray-300"}>
                            {tick === "sent" && "✓"}
                            {tick === "delivered" && "✓✓"}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            <div ref={endRef} />
          </div>

          {/* INPUT */}
          <form onSubmit={sendMessage} className="px-3 py-3 bg-black/30 border-t border-white/10 flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a message"
              className="flex-1 bg-white/10 backdrop-blur-md border border-white/10 rounded-full px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-[#00a884]"
            />
            <button
              type="submit"
              disabled={!input.trim() || isSending}
              className="px-3 py-2 rounded-full bg-[#00a884] text-black text-sm font-medium disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </div>

        {/* INFO BOX */}
        <div className="w-full md:w-1/3 p-4 backdrop-blur-xl bg-white/5 border border-white/10 rounded-2xl shadow-lg text-gray-200 text-sm flex flex-col">
          <h2 className="font-bold text-base mb-2">How This Demo Works</h2>
          <p className="leading-relaxed text-xs">
            - Switch between <span className="font-semibold">Student</span> and <span className="font-semibold">Vendor</span> using the buttons above.<br/>
            - Type a message and hit <span className="font-semibold">Send</span>.<br/>
            - Your message appears in green bubbles; Bukka AI responses in gray.<br/>
            - Ticks show status: single ✓ = sent, double ✓✓ = delivered.<br/>
            - Click <span className="font-semibold">Reset</span> to clear the chat.
          </p>
        </div>

      </div>

      <style>{`
        @keyframes gradient-x {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        .animate-gradient-x {
          animation: gradient-x 15s ease infinite;
        }
      `}</style>
    </div>
  );
}
