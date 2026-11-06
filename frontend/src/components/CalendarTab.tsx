import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock, Search } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage } from '../services/errors';
import { formatDate } from '../lib/format';

export default function CalendarTab() {
  const [category, setCategory] = useState('all');
  const [search, setSearch] = useState('');
  const query = useQuery({ queryKey: ['events'], queryFn: () => api.events(50) });

  const events = query.data ?? [];
  const categories = Array.from(new Set(events.map((e) => e.event_type))).sort();
  const q = search.trim().toLowerCase();
  const shown = events.filter(
    (e) =>
      (category === 'all' || e.event_type === category) &&
      (!q || e.title.toLowerCase().includes(q) || (e.description ?? '').toLowerCase().includes(q)),
  );
  const chip = (active: boolean) =>
    `rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap ${
      active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100'
    }`;

  return (
    <section className="mx-auto w-full max-w-5xl space-y-4 p-3 sm:p-6" aria-labelledby="cal-h">
      <h1 id="cal-h" className="text-xl font-extrabold text-slate-900 dark:text-white">
        Academic calendar
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Upcoming events from today. For attendance, make-up exam or NPTEL/NEC rules, ask the AI Chat.
      </p>

      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:bg-slate-900">
        <div className="flex gap-1.5 overflow-x-auto" role="group" aria-label="Filter by type">
          <button type="button" className={chip(category === 'all')} aria-pressed={category === 'all'} onClick={() => setCategory('all')}>
            All
          </button>
          {categories.map((c) => (
            <button key={c} type="button" className={chip(category === c)} aria-pressed={category === c} onClick={() => setCategory(c)}>
              {c}
            </button>
          ))}
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
          <label htmlFor="cal-search" className="sr-only">Search events</label>
          <input
            id="cal-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search events"
            className="w-full rounded-xl border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white"
          />
        </div>
      </div>

      {query.isPending ? (
        <div className="space-y-3" aria-busy="true" aria-label="Loading events">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />
          ))}
        </div>
      ) : query.isError ? (
        <div role="alert" className="rounded-2xl border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          {errorMessage(query.error)}{' '}
          <button type="button" onClick={() => query.refetch()} className="font-semibold underline">
            Retry
          </button>
        </div>
      ) : shown.length === 0 ? (
        <p className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
          No events match.
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((e) => (
            <li key={e.id} className="flex flex-col justify-between gap-2 rounded-2xl border border-slate-200 bg-white p-4 sm:flex-row sm:items-center dark:border-slate-800 dark:bg-slate-900">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-bold uppercase text-blue-800 dark:bg-blue-950 dark:text-blue-200">
                    {e.event_type}
                  </span>
                  {e.suppresses_timetable && (
                    <span className="rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">No regular classes</span>
                  )}
                </div>
                <h2 className="mt-1 text-sm font-bold text-slate-900 dark:text-white">{e.title}</h2>
                {e.description && <p className="text-xs text-slate-600 dark:text-slate-300">{e.description}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-100">
                <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                {formatDate(e.start_date)}
                {e.end_date !== e.start_date && ` – ${formatDate(e.end_date)}`}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
