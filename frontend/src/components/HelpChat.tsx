import { useState } from "react";
import type { Role } from "../types";
import { askHelp } from "../api/client";

type Message = { from: "assistant" | "user"; text: string; suggestions?: string[] };

export function HelpChat({ surface, role, activeArea }: { surface: "signin" | "workspace"; role?: Role; activeArea?: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { from: "assistant", text: surface === "signin" ? "Need help signing in? Ask about credentials, roles, or access." : "I can help with the current workspace, queries, permissions, and next steps." },
  ]);

  async function submit(value = question) {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    setQuestion("");
    setMessages((current) => [...current, { from: "user", text: trimmed }]);
    setIsLoading(true);
    try {
      const response = await askHelp({ question: trimmed, surface, role, active_area: activeArea });
      setMessages((current) => [...current, { from: "assistant", text: response.answer, suggestions: response.suggestions }]);
    } catch {
      setMessages((current) => [...current, { from: "assistant", text: "I could not reach the help service. Check that the backend is running and try again." }]);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <aside className={`help-chat ${isOpen ? "help-chat-open" : ""}`} aria-label="In-product help">
      {isOpen && (
        <div className="help-chat-panel">
          <div className="help-chat-heading"><strong>QE guide</strong><button type="button" className="chat-close" onClick={() => setIsOpen(false)} aria-label="Close help">×</button></div>
          <div className="help-chat-messages">
            {messages.map((message, index) => (
              <div className={`help-message help-message-${message.from}`} key={`${message.from}-${index}`}>
                <p>{message.text}</p>
                {message.suggestions?.map((suggestion) => <button type="button" className="help-suggestion" key={suggestion} onClick={() => submit(suggestion)}>{suggestion}</button>)}
              </div>
            ))}
            {isLoading && <div className="help-message help-message-assistant"><p>Thinking...</p></div>}
          </div>
          <form className="help-chat-form" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            <input aria-label="Ask the QE guide" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question..." />
            <button type="submit" disabled={!question.trim() || isLoading} aria-label="Send question">Send</button>
          </form>
        </div>
      )}
      <button type="button" className="help-chat-toggle" onClick={() => setIsOpen((open) => !open)} aria-expanded={isOpen}>? <span>Help</span></button>
    </aside>
  );
}