import { Suspense, lazy, useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/auth-context';
import { ToastProvider } from './context/ToastContext';
import { Navbar, type Tab } from './components/Navbar';
import { LoginScreen } from './components/LoginScreen';
import { ErrorBoundary } from './components/ErrorBoundary';
import { OfflineBanner } from './components/OfflineBanner';
import { NotFound } from './components/NotFound';
import { createQueryClient } from './queryClient';
import type { User } from './types';

const ChatTab = lazy(() => import('./components/ChatTab'));
const ScheduleTab = lazy(() => import('./components/ScheduleTab'));
const CalendarTab = lazy(() => import('./components/CalendarTab'));
const AdminTab = lazy(() => import('./components/AdminTab'));

function Loading() {
  return (
    <div role="status" className="p-10 text-center text-sm text-slate-600 dark:text-slate-300">
      Loading…
    </div>
  );
}

function MainLayout({ user }: { user: User }) {
  const isAdmin = user.role === 'admin';
  const [requested, setTab] = useState<Tab>(isAdmin ? 'admin' : 'chat');
  const tab: Tab = requested === 'admin' && !isAdmin ? 'chat' : requested;

  return (
    <>
      <Navbar activeTab={tab} setActiveTab={setTab} />
      <main className="flex flex-1 flex-col">
        <Suspense fallback={<Loading />}>
          {tab === 'chat' && <ChatTab />}
          {tab === 'schedule' && <ScheduleTab />}
          {tab === 'calendar' && <CalendarTab />}
          {tab === 'admin' && isAdmin && <AdminTab />}
        </Suspense>
      </main>
    </>
  );
}

function Shell() {
  const { user, loading } = useAuth();
  if (window.location.pathname !== '/' && window.location.pathname !== '/index.html') {
    return <NotFound />;
  }
  if (loading) return <Loading />;
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <OfflineBanner />
      {user ? <MainLayout key={user.email} user={user} /> : <LoginScreen />}
    </div>
  );
}

const queryClient = createQueryClient();

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <Shell />
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
