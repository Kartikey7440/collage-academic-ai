const ACCESS = 'mits_access';
const REFRESH = 'mits_refresh';
export const CHAT_PREFIX = 'mits_chat_';

export const tokens = {
  access: (): string | null => sessionStorage.getItem(ACCESS),
  refresh: (): string | null => sessionStorage.getItem(REFRESH),
  set(access: string, refresh?: string): void {
    sessionStorage.setItem(ACCESS, access);
    if (refresh) sessionStorage.setItem(REFRESH, refresh);
  },
  clear(): void {
    sessionStorage.removeItem(ACCESS);
    sessionStorage.removeItem(REFRESH);
  },
};

/** Remove tokens and every per-user cache kept in sessionStorage. */
export function clearAllSessionData(): void {
  tokens.clear();
  const doomed: string[] = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    if (key && key.startsWith(CHAT_PREFIX)) doomed.push(key);
  }
  doomed.forEach((k) => sessionStorage.removeItem(k));
}

// Older builds kept tokens in localStorage; make sure none are left behind.
export function purgeLegacyStorage(): void {
  localStorage.removeItem('mits_access_token');
  localStorage.removeItem('mits_refresh_token');
}

