import type { ZodType } from 'zod';
import {
  ApiError,
  ForbiddenError,
  NetworkError,
  ResponseShapeError,
  ServerError,
  UnauthorizedError,
  ValidationError,
} from './errors';
import {
  AccessTokenSchema,
  ChatReplySchema,
  EventListSchema,
  FacultyListSchema,
  NextClassSchema,
  ReviewItemSchema,
  ReviewQueueSchema,
  SlotListSchema,
  SuppressedSchema,
  TokenPairSchema,
  UserSchema,
} from './schemas';
import { clearAllSessionData, tokens } from './session';

const BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api/v1';
const DEFAULT_TIMEOUT_MS = 15_000;
const CHAT_TIMEOUT_MS = 30_000;

let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(fn: (() => void) | null): void {
  onSessionExpired = fn;
}

interface SendInit {
  method: string;
  body?: unknown;
  auth: boolean;
}

async function send(path: string, init: SendInit, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';
  const access = tokens.access();
  if (init.auth && access) headers.Authorization = `Bearer ${access}`;
  try {
    return await fetch(BASE + path, {
      method: init.method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: ctrl.signal,
    });
  } catch {
    throw new NetworkError(
      ctrl.signal.aborted
        ? 'The request timed out. Please try again.'
        : 'Cannot reach the server. Check your connection.',
    );
  } finally {
    clearTimeout(timer);
  }
}

async function readDetails(res: Response): Promise<string[]> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') return [detail];
      if (Array.isArray(detail)) {
        return detail.map((d: unknown) =>
          d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d),
        );
      }
    }
  } catch {
    // body was not JSON; fall through to a generic message
  }
  return [];
}

async function toApiError(res: Response): Promise<ApiError> {
  const details = await readDetails(res);
  switch (res.status) {
    case 401:
      return new UnauthorizedError(details[0] ?? 'Please sign in again.', 401);
    case 403:
      return new ForbiddenError(details[0] ?? 'You do not have access to this.', 403);
    case 400:
    case 409:
    case 422:
      return new ValidationError(details.length ? details : ['The request was not accepted.'], res.status);
    case 404:
      return new ApiError(details[0] ?? 'Not found.', 404);
    default:
      return new ServerError('The server had a problem. Please try again shortly.', res.status);
  }
}

let refreshing: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const refreshToken = tokens.refresh();
  if (!refreshToken) return false;
  try {
    const res = await send(
      '/auth/refresh',
      { method: 'POST', body: { refresh_token: refreshToken }, auth: false },
      DEFAULT_TIMEOUT_MS,
    );
    if (!res.ok) return false;
    const parsed = AccessTokenSchema.safeParse(await res.json());
    if (!parsed.success) return false;
    tokens.set(parsed.data.access_token);
    return true;
  } catch {
    return false;
  }
}

function refreshAccess(): Promise<boolean> {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

interface RequestOptions<T> {
  method?: string;
  body?: unknown;
  schema: ZodType<T>;
  timeoutMs?: number;
  auth?: boolean;
}

export async function request<T>(path: string, opts: RequestOptions<T>): Promise<T> {
  const { method = 'GET', body, schema, timeoutMs = DEFAULT_TIMEOUT_MS, auth = true } = opts;
  const attempt = () => send(path, { method, body, auth }, timeoutMs);

  let res = await attempt();
  if (auth && res.status === 401) {
    const refreshed = await refreshAccess();
    if (refreshed) res = await attempt();
    if (!refreshed || res.status === 401) {
      clearAllSessionData();
      onSessionExpired?.();
      throw new UnauthorizedError('Your session expired', 401);
    }
  }
  if (!res.ok) throw await toApiError(res);

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new ResponseShapeError('The server sent an unexpected response. Please try again.');
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    throw new ResponseShapeError('The server sent an unexpected response. Please try again.');
  }
  return parsed.data;
}

export interface ChatTurn {
  role: 'user' | 'model';
  text: string;
}

export const api = {
  async login(email: string, password: string): Promise<void> {
    const pair = await request('/auth/login', {
      method: 'POST',
      body: { email, password },
      schema: TokenPairSchema,
      auth: false,
    });
    tokens.set(pair.access_token, pair.refresh_token);
  },
  me: () => request('/auth/me', { schema: UserSchema }),

  slotsForDay: (day: number) => request(`/timetable/day/${day}`, { schema: SlotListSchema }),
  nextClass: () => request('/timetable/next-class', { schema: NextClassSchema }),
  /** The server's idea of "today" (honours the demo clock). */
  serverToday: () => request('/timetable/suppressed', { schema: SuppressedSchema }),
  events: (limit = 50) => request(`/events/upcoming?limit=${limit}`, { schema: EventListSchema }),

  chat: (message: string, history: ChatTurn[]) =>
    request('/chat', {
      method: 'POST',
      body: { message, history },
      schema: ChatReplySchema,
      timeoutMs: CHAT_TIMEOUT_MS,
    }),

  reviewQueue: () => request('/admin/review-queue', { schema: ReviewQueueSchema }),
  facultyList: () => request('/admin/faculty', { schema: FacultyListSchema }),
  patchSlot: (
    id: number,
    body: { faculty_codes?: string[]; room?: string | null; mark_reviewed?: boolean },
  ) => request(`/admin/slots/${id}`, { method: 'PATCH', body, schema: ReviewItemSchema }),
};
