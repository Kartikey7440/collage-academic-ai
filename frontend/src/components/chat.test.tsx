import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatTab from './ChatTab';
import { tokens, clearAllSessionData } from '../services/session';
import { loadChat, saveChat, type ChatMessage } from '../lib/chatStore';
import { callsTo, mockFetch } from '../test/mockFetch';
import { renderWithProviders } from '../test/render';
import { chatReply, student } from '../test/fixtures';

async function openChat() {
  const user = userEvent.setup();
  renderWithProviders(<ChatTab />);
  const box = (await screen.findByLabelText('Your message')) as HTMLTextAreaElement;
  const send = screen.getByRole('button', { name: 'Send message' }) as HTMLButtonElement;
  return { user, box, send };
}

describe('chat', () => {
  it('shows a loading state, blocks sending, then the fallback badge, seconds and assistant clock', async () => {
    tokens.set('a', 'r');
    let release: () => void = () => {};
    mockFetch({
      'GET /auth/me': { body: student },
      'POST /chat': async () => {
        await new Promise<void>((r) => {
          release = r;
        });
        return { body: chatReply({ fallback: true, elapsed_ms: 2300, assistant_time: 'Monday 10:30 AM' }) };
      },
    });
    const { user, box, send } = await openChat();
    await user.type(box, 'next class?');
    await user.click(send);
    expect(await screen.findByText('Looking that up...')).toBeTruthy();
    await user.type(box, 'another');
    expect(send.disabled).toBe(true);
    release();
    expect(await screen.findByText('Quick answer (AI busy)')).toBeTruthy();
    expect(screen.getByText('2.3 s')).toBeTruthy();
    expect(screen.getByText('Monday 10:30 AM')).toBeTruthy();
  });

  it('shows an error bubble with Retry that resends without duplicating the question', async () => {
    tokens.set('a', 'r');
    let calls = 0;
    mockFetch({
      'GET /auth/me': { body: student },
      'POST /chat': () => (calls++ === 0 ? { status: 500, body: {} } : { body: chatReply({ reply: 'Second try worked' }) }),
    });
    const { user, box } = await openChat();
    await user.type(box, 'hello');
    await user.keyboard('{Enter}');
    const retry = await screen.findByRole('button', { name: /retry/i });
    expect(screen.getByText(/server had a problem/i)).toBeTruthy();
    await user.click(retry);
    expect(await screen.findByText('Second try worked')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
    expect(screen.getAllByText('hello')).toHaveLength(1);
  });

  it('renders unsafe HTML in a reply as plain text', async () => {
    tokens.set('a', 'r');
    mockFetch({
      'GET /auth/me': { body: student },
      'POST /chat': { body: chatReply({ reply: '<img src=x onerror=alert(1)> **Bold** text\n* item one\n* item two' }) },
    });
    const { user, box } = await openChat();
    await user.type(box, 'hi');
    await user.keyboard('{Enter}');
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText('Bold').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('blocks blank messages and shows the 500-character counter', async () => {
    tokens.set('a', 'r');
    mockFetch({ 'GET /auth/me': { body: student } });
    const { user, box, send } = await openChat();
    expect(send.disabled).toBe(true);
    await user.type(box, '   ');
    expect(send.disabled).toBe(true);
    await user.clear(box);
    await user.type(box, 'abc');
    expect(screen.getByText('3/500')).toBeTruthy();
    expect(send.disabled).toBe(false);
    expect(box.maxLength).toBe(500);
  });

  it('Enter sends and Shift+Enter inserts a new line', async () => {
    tokens.set('a', 'r');
    const f = mockFetch({ 'GET /auth/me': { body: student }, 'POST /chat': { body: chatReply() } });
    const { user, box } = await openChat();
    await user.type(box, 'line1{Shift>}{Enter}{/Shift}line2');
    expect(box.value).toBe('line1\nline2');
    expect(callsTo(f, 'POST', '/chat')).toBe(0);
    await user.keyboard('{Enter}');
    await screen.findByText('You have Data Structures at 9:00 AM.');
    expect(callsTo(f, 'POST', '/chat')).toBe(1);
  });
});

describe('chat storage', () => {
  const msg = (i: number): ChatMessage => ({ id: String(i), role: 'user', content: `m${i}` });

  it('keeps only the last 50 messages and is wiped on sign out', () => {
    saveChat('mits_chat_1', Array.from({ length: 60 }, (_, i) => msg(i)));
    const loaded = loadChat('mits_chat_1');
    expect(loaded).toHaveLength(50);
    expect(loaded[0].content).toBe('m10');
    clearAllSessionData();
    expect(loadChat('mits_chat_1')).toEqual([]);
  });

  it('ignores corrupted stored data', () => {
    sessionStorage.setItem('mits_chat_1', '{not json');
    expect(loadChat('mits_chat_1')).toEqual([]);
  });
});

