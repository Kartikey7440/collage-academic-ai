import { createContext, useContext } from 'react';
import type { User } from '../types';

export type Theme = 'light' | 'dark';

export interface AuthContextType {
  user: User | null;
  loading: boolean;
  theme: Theme;
  toggleTheme: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}

