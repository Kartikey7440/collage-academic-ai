import { useState, type FormEvent } from 'react';
import { useAuth } from '../context/auth-context';
import { errorMessage } from '../services/errors';

export function LoginScreen() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const field =
    'w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white';

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-4">
      <form onSubmit={submit} className="w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-lg dark:border-slate-700 dark:bg-slate-900">
        <div className="mb-5 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-xl font-extrabold text-white" aria-hidden="true">
            Δ
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">MITS Smart Campus</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Sign in with your college account.</p>
        </div>

        {error && (
          <p role="alert" className="mb-4 rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}

        <label htmlFor="login-email" className="mb-1 block text-sm font-semibold text-slate-700 dark:text-slate-200">
          Email
        </label>
        <input id="login-email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />

        <label htmlFor="login-password" className="mb-1 mt-4 block text-sm font-semibold text-slate-700 dark:text-slate-200">
          Password
        </label>
        <input id="login-password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />

        <button
          type="submit"
          disabled={busy}
          className="mt-6 w-full rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}
