import { z } from 'zod';
import type { ChatTurn } from '../services/api';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  kind?: 'error';
  retryText?: string;
  fallback?: boolean;
  elapsedMs?: number;
  assistantTime?: string;
  tools?: string[];
}

const StoredSchema = z.array(
  z.object({
    id: z.string(),
    role: z.enum(['user', 'assistant']),
    content: z.string(),
    kind: z.literal('error').optional(),
    retryText: z.string().optional(),
    fallback: z.boolean().optional(),
    elapsedMs: z.number().optional(),
    assistantTime: z.string().optional(),
    tools: z.array(z.string()).optional(),
  }),
);

export const MAX_STORED = 50;

export function loadChat(key: string): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return [];
    const parsed = StoredSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data.slice(-MAX_STORED) : [];
  } catch {
    return [];
  }
}

export function saveChat(key: string, messages: ChatMessage[]): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(messages.slice(-MAX_STORED)));
  } catch {
    // storage full or unavailable: the chat still works, it just is not remembered
  }
}

/** Last 12 real turns (the API limit); error bubbles are never sent. */
export function toHistory(messages: ChatMessage[]): ChatTurn[] {
  return messages
    .filter((m) => m.kind !== 'error')
    .slice(-12)
    .map((m) => ({ role: m.role === 'user' ? 'user' : 'model', text: m.content.slice(0, 1000) }));
}

