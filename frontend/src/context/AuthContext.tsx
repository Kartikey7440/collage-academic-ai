import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { User } from '../types';
import { api, setSessionExpiredHandler } from '../services/api';
import { clearAllSessionData, purgeLegacyStorage, tokens } from '../services/session';
import { useToast } from './toast-context';
import { AuthContext, type Theme } from './auth-context';

function initialTheme(): Theme {
  const saved = localStorage.getItem('mits_theme');
  if (saved === 'dark' || saved === 'light') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(() => tokens.access() !== null);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('mits_theme', theme);
  }, [theme]);

  useEffect(() => {
    purgeLegacyStorage();
    setSessionExpiredHandler(() => {
      setUser(null);
      queryClient.clear();
      toast.push('error', 'Your session expired');
    });
    if (tokens.access()) {
      api
        .me()
        .then(setUser)
        .catch(() => {
          clearAllSessionData();
          setUser(null);
        })
        .finally(() => setLoading(false));
    }
    return () => setSessionExpiredHandler(null);
  }, [queryClient, toast]);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    setUser(await api.me());
  }, []);

  const logout = useCallback(() => {
    clearAllSessionData();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);

  return (
    <AuthContext.Provider value={{ user, loading, theme, toggleTheme, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
