import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, setSessionExpiredHandler } from './api';
import {
  ForbiddenError,
  NetworkError,
  ResponseShapeError,
  ServerError,
  UnauthorizedError,
  ValidationError,
} from './errors';
import { tokens } from './session';
import { mockFetch } from '../test/mockFetch';

afterEach(() => setSessionExpiredHandler(null));

describe('api client', () => {
  it('login keeps tokens in sessionStorage only', async () => {
    mockFetch({ 'POST /auth/login': { body: { access_token: 'A', refresh_token: 'R' } } });
    await api.login('a@b.c', 'pw');
    expect(sessionStorage.getItem('mits_access')).toBe('A');
    expect(sessionStorage.getItem('mits_refresh')).toBe('R');
    expect(localStorage.length).toBe(0);
  });

  it('on 401 refreshes once, retries once and uses the new token', async () => {
    tokens.set('old', 'ref');
    let n = 0;
    const f = mockFetch({
      'GET /timetable/day/0': () => (n++ === 0 ? { status: 401, body: { detail: 'expired' } } : { body: [] }),
      'POST /auth/refresh': { body: { access_token: 'new' } },
    });
    await expect(api.slotsForDay(0)).resolves.toEqual([]);
    expect(tokens.access()).toBe('new');
    expect(f).toHaveBeenCalledTimes(3);
    const retryInit = f.mock.calls[2][1] as RequestInit;
    expect((retryInit.headers as Record<string, string>).Authorization).toBe('Bearer new');
  });

  it('signs out with "Your session expired" when refresh fails', async () => {
    tokens.set('old', 'ref');
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    mockFetch({
      'GET /timetable/day/0': { status: 401 },
      'POST /auth/refresh': { status: 401, body: { detail: 'bad' } },
    });
    const err = await api.slotsForDay(0).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UnauthorizedError);
    expect((err as Error).message).toBe('Your session expired');
    expect(expired).toHaveBeenCalledOnce();
    expect(tokens.access()).toBeNull();
  });

  it('a wrong password is not treated as an expired session', async () => {
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    mockFetch({ 'POST /auth/login': { status: 401, body: { detail: 'Incorrect email or password.' } } });
    const err = await api.login('a@b.c', 'bad').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UnauthorizedError);
    expect((err as Error).message).toBe('Incorrect email or password.');
    expect(expired).not.toHaveBeenCalled();
  });

  it('maps 403 to ForbiddenError', async () => {
    tokens.set('a', 'r');
    mockFetch({ 'GET /admin/review-queue': { status: 403, body: { detail: 'Admins only' } } });
    await expect(api.reviewQueue()).rejects.toBeInstanceOf(ForbiddenError);
  });

  it('maps 422 to ValidationError with the server messages', async () => {
    tokens.set('a', 'r');
    mockFetch({
      'PATCH /admin/slots/1': { status: 422, body: { detail: [{ msg: 'Unknown faculty code(s): ZZ' }] } },
    });
    const err = await api.patchSlot(1, { faculty_codes: ['ZZ'] }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ValidationError);
    expect((err as ValidationError).messages).toEqual(['Unknown faculty code(s): ZZ']);
  });

  it('maps 5xx to ServerError and a failed fetch to NetworkError', async () => {
    tokens.set('a', 'r');
    mockFetch({ 'GET /events/upcoming': { status: 503, body: {} } });
    await expect(api.events()).rejects.toBeInstanceOf(ServerError);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(api.events()).rejects.toBeInstanceOf(NetworkError);
  });

  it('rejects responses with an unexpected shape', async () => {
    tokens.set('a', 'r');
    mockFetch({ 'GET /timetable/day/0': { body: { slots: 'nope' } } });
    await expect(api.slotsForDay(0)).rejects.toBeInstanceOf(ResponseShapeError);
  });

  it('times out after 15 seconds', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: unknown, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
          }),
      ),
    );
    const pending = api.serverToday().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(15_000);
    const err = await pending;
    expect(err).toBeInstanceOf(NetworkError);
    expect((err as Error).message).toMatch(/timed out/);
  });
});

