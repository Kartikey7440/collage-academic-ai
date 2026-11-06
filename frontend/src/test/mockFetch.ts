import { vi } from 'vitest';

export interface Spec {
  status?: number;
  body?: unknown;
}
export type Route = Spec | ((req: { url: URL; init: RequestInit }) => Spec | Promise<Spec>);

/** Replace global fetch with a router keyed "METHOD /path" (path relative to /api/v1). No network. */
export function mockFetch(routes: Record<string, Route>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://localhost');
    const key = `${(init.method ?? 'GET').toUpperCase()} ${url.pathname.replace('/api/v1', '')}`;
    const route = routes[key];
    if (!route) {
      console.error(`Unmocked request: ${key}`);
      throw new TypeError(`Unmocked request: ${key}`);
    }
    const spec = typeof route === 'function' ? await route({ url, init }) : route;
    const payload = spec.body === undefined ? {} : spec.body;
    return new Response(JSON.stringify(payload), {
      status: spec.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

export function callsTo(fn: ReturnType<typeof mockFetch>, method: string, path: string): number {
  return fn.mock.calls.filter(([input, init]) => {
    const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://localhost');
    return (init?.method ?? 'GET').toUpperCase() === method && url.pathname.endsWith(path);
  }).length;
}

