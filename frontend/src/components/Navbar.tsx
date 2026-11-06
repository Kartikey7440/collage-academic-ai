import type { ComponentType } from 'react';
import { Bot, Calendar, CalendarDays, GraduationCap, LogOut, Moon, ShieldCheck, Sun } from 'lucide-react';
import { useAuth } from '../context/auth-context';

export type Tab = 'chat' | 'schedule' | 'calendar' | 'admin';

interface TabDef {
  id: Tab;
  label: string;
  Icon: ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

const TABS: TabDef[] = [
  { id: 'chat', label: 'AI Chat', Icon: Bot },
  { id: 'schedule', label: 'Schedule', Icon: Calendar },
  { id: 'calendar', label: 'Calendar', Icon: CalendarDays },
  { id: 'admin', label: 'Admin', Icon: ShieldCheck, adminOnly: true },
];

interface NavbarProps {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
}

export function Navbar({ activeTab, setActiveTab }: NavbarProps) {
  const { user, logout, theme, toggleTheme } = useAuth();
  const visible = TABS.filter((t) => !t.adminOnly || user?.role === 'admin');

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-2 px-3 sm:px-6">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-lg font-extrabold text-white" aria-hidden="true">
            Δ
          </div>
          <span className="hidden text-base font-bold text-slate-900 sm:inline dark:text-white">MITS Campus</span>
        </div>

        <nav aria-label="Main" className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
          {visible.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              aria-current={activeTab === id ? 'page' : undefined}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold sm:px-3 ${
                activeTab === id
                  ? 'bg-white text-blue-700 shadow-xs dark:bg-slate-900 dark:text-blue-300'
                  : 'text-slate-700 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white'
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              <span className="sr-only sm:not-sr-only">{label}</span>
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-1 sm:gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="rounded-xl p-2 text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
          </button>
          {user && (
            <>
              <div className="hidden text-right sm:block">
                <div className="text-xs font-semibold text-slate-900 dark:text-white">{user.email.split('@')[0]}</div>
                <div className="text-[11px] text-slate-600 dark:text-slate-300">
                  {user.branch_code ? `${user.branch_code} · Sem ${user.semester ?? '-'}` : user.role}
                </div>
              </div>
              <GraduationCap className="hidden h-5 w-5 text-blue-600 sm:block" aria-hidden="true" />
              <button
                type="button"
                onClick={logout}
                aria-label="Sign out"
                className="rounded-xl p-2 text-slate-700 hover:bg-slate-100 hover:text-red-600 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
