import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Bot, Check, Clock, Copy, RotateCcw, Send, Sparkles, Trash2, User as UserIcon, Zap } from 'lucide-react';
import { useAuth } from '../context/auth-context';
import { useToast } from '../context/toast-context';
import { api } from '../services/api';
import { errorMessage } from '../services/errors';
import { CHAT_PREFIX } from '../services/session';
import { loadChat, saveChat, toHistory, type ChatMessage } from '../lib/chatStore';
import { RichText } from './RichText';

const MAX_LEN = 500;
const SUGGESTIONS = [
  'What is my next class?',
  'What classes do I have today?',
  'What is my schedule for tomorrow?',
  'Show my classes for the week',
  'When are the next exams?',
  'Are there any holidays coming up?',
];

let counter = 0;
const newId = () => `${Date.now()}-${counter++}`;

export default function ChatTab() {
  const { user } = useAuth();
  if (!user) return null;
  if (user.role === 'admin') {
    return (
      <section className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center dark:border-slate-700 dark:bg-slate-900">
        <Bot className="mx-auto h-10 w-10 text-slate-500" aria-hidden="true" />
        <h1 className="mt-3 text-lg font-bold text-slate-900 dark:text-white">Chat is for students and faculty</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          The assistant answers from a student&apos;s or teacher&apos;s own timetable, so it is not available to admin accounts. Use the Admin tab to review flagged timetable slots.
        </p>
      </section>
    );
  }
  return <ChatPanel storageKey={`${CHAT_PREFIX}${user.id ?? user.email}`} />;
}

function ChatPanel({ storageKey }: { storageKey: string }) {
  const toast = useToast();
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadChat(storageKey));
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    saveChat(storageKey, messages);
  }, [storageKey, messages]);

  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, pending]);

  const onScroll = () => {
    const el = listRef.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const run = async (text: string, prior: ChatMessage[]) => {
    setPending(true);
    try {
      const r = await api.chat(text, toHistory(prior));
      setMessages((m) => [
        ...m,
        {
          id: newId(),
          role: 'assistant',
          content: r.reply || 'I could not find an answer to that.',
          fallback: r.fallback,
          elapsedMs: r.elapsed_ms,
          assistantTime: r.assistant_time,
          tools: r.tools_used.map((t) => t.name),
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { id: newId(), role: 'assistant', kind: 'error', content: errorMessage(e), retryText: text },
      ]);
    } finally {
      setPending(false);
    }
  };

  const send = (raw: string) => {
    const text = raw.trim();
    if (!text || pending) return;
    stick.current = true;
    const prior = messages;
    setMessages([...messages, { id: newId(), role: 'user', content: text }]);
    setInput('');
    void run(text, prior);
  };

  const retry = (errorId: string) => {
    if (pending) return;
    const idx = messages.findIndex((m) => m.id === errorId);
    const failed = messages[idx];
    if (idx < 1 || !failed?.retryText) return;
    stick.current = true;
    setMessages(messages.slice(0, idx));
    void run(failed.retryText, messages.slice(0, idx - 1));
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  };

  const copy = async (m: ChatMessage) => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(m.id);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.push('error', 'Could not copy. Select the text and copy it manually.');
    }
  };

  const clear = () => {
    setMessages([]);
    sessionStorage.removeItem(storageKey);
  };

  return (
    <section className="mx-auto flex h-[calc(100dvh-4rem)] w-full max-w-4xl flex-col p-3 sm:p-4" aria-label="AI chat">
      <div
        ref={listRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1"
      >
        {messages.length === 0 && (
          <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            <p className="font-semibold text-slate-900 dark:text-white">Hi! Ask me about your classes or the academic calendar.</p>
            <p className="mt-1">Pick a suggestion below or type your own question.</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {m.role === 'assistant' && (
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white" aria-hidden="true">
                <Bot className="h-4 w-4" />
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${
                m.role === 'user'
                  ? 'bg-blue-700 text-white'
                  : m.kind === 'error'
                    ? 'border border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100'
                    : 'border border-slate-200 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100'
              }`}
            >
              {m.role === 'user' ? <p className="whitespace-pre-wrap break-words">{m.content}</p> : <RichText text={m.content} />}

              {m.kind === 'error' && m.retryText && (
                <button
                  type="button"
                  onClick={() => retry(m.id)}
                  disabled={pending}
                  className="mt-2 inline-flex items-center gap-1 rounded-lg bg-red-700 px-3 py-1 text-xs font-semibold text-white disabled:opacity-60"
                >
                  <RotateCcw className="h-3 w-3" aria-hidden="true" /> Retry
                </button>
              )}

              {m.role === 'assistant' && m.kind !== 'error' && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-300">
                  {m.fallback && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-900">
                      <Zap className="h-3 w-3" aria-hidden="true" /> Quick answer (AI busy)
                    </span>
                  )}
                  {m.elapsedMs !== undefined && <span>{(m.elapsedMs / 1000).toFixed(1)} s</span>}
                  {m.assistantTime && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                      <Clock className="h-3 w-3" aria-hidden="true" /> {m.assistantTime}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void copy(m)}
                    aria-label="Copy reply"
                    className="ml-auto rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
                  >
                    {copied === m.id ? <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
                  </button>
                </div>
              )}
            </div>
            {m.role === 'user' && (
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200" aria-hidden="true">
                <UserIcon className="h-4 w-4" />
              </div>
            )}
          </div>
        ))}
        {pending && (
          <div role="status" className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
            <span className="flex gap-1" aria-hidden="true">
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-600" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-600 [animation-delay:150ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-blue-600 [animation-delay:300ms]" />
            </span>
            Looking that up...
          </div>
        )}
      </div>

      <div className="flex gap-2 overflow-x-auto py-2" role="group" aria-label="Suggested questions">
        <Sparkles className="mt-1.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            disabled={pending}
            onClick={() => send(s)}
            className="shrink-0 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-800 hover:border-blue-600 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          >
            {s}
          </button>
        ))}
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 dark:border-slate-600 dark:bg-slate-900">
        <button
          type="button"
          onClick={clear}
          aria-label="Clear conversation"
          disabled={messages.length === 0}
          className="rounded-xl p-2 text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" />
        </button>
        <div className="flex-1">
          <label htmlFor="chat-input" className="sr-only">Your message</label>
          <textarea
            id="chat-input"
            rows={1}
            value={input}
            maxLength={MAX_LEN}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about your timetable or the calendar"
            className="max-h-32 w-full resize-none bg-transparent px-1 py-1 text-sm text-slate-900 placeholder:text-slate-500 dark:text-white"
          />
          <div className="text-right text-[11px] text-slate-600 dark:text-slate-300" aria-live="off">
            {input.length}/{MAX_LEN}
          </div>
        </div>
        <button
          type="submit"
          disabled={pending || input.trim() === ''}
          aria-label="Send message"
          className="rounded-xl bg-blue-700 p-2.5 text-white hover:bg-blue-800 disabled:opacity-40"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
        </button>
      </form>
    </section>
  );
}
