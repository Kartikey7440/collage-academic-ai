import { useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { Clock, FlaskConical, MapPin, User as UserIcon } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage } from '../services/errors';
import { DAY_NAMES, formatTime, toMinutes, weekdayOf } from '../lib/format';
import type { Slot } from '../types';

const DAYS = [0, 1, 2, 3, 4, 5] as const;

function ConfirmTag() {
  return (
    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900">To be confirmed</span>
  );
}

function SlotCard({ slot, showNames }: { slot: Slot; showNames: boolean }) {
  const faculty = slot.faculty.map((f) => (showNames ? f.name : f.code)).join(', ');
  const tone = slot.subject.is_lab
    ? 'border-violet-300 bg-violet-50 dark:border-violet-700 dark:bg-violet-950'
    : 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950';
  return (
    <div className={`rounded-xl border p-2 text-xs ${tone} ${slot.needs_review ? 'border-dashed border-amber-500' : ''}`}>
      <div className="flex flex-wrap items-center gap-1">
        <span className="font-bold text-slate-900 dark:text-white">{slot.subject.name}</span>
        {slot.subject.is_lab && (
          <span className="inline-flex items-center gap-0.5 rounded bg-violet-200 px-1.5 py-0.5 text-[10px] font-bold text-violet-900">
            <FlaskConical className="h-3 w-3" aria-hidden="true" /> Lab
          </span>
        )}
        {slot.batch && (
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-900">Batch {slot.batch}</span>
        )}
        {slot.needs_review && <ConfirmTag />}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-slate-700 dark:text-slate-200">
        <span className="inline-flex items-center gap-1">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {slot.room ? `Room ${slot.room}` : 'Room to be announced'}
        </span>
        <span className="inline-flex items-center gap-1" title={slot.faculty.map((f) => f.name).join(', ')}>
          <UserIcon className="h-3 w-3" aria-hidden="true" />
          {faculty || 'Faculty to be announced'}
        </span>
      </div>
    </div>
  );
}

function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-2xl border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
      {message}{' '}
      <button type="button" onClick={onRetry} className="font-semibold underline">
        Retry
      </button>
    </div>
  );
}

export default function ScheduleTab() {
  const today = useQuery({ queryKey: ['server-today'], queryFn: api.serverToday });
  const next = useQuery({ queryKey: ['next-class'], queryFn: api.nextClass });
  const week = useQueries({
    queries: DAYS.map((d) => ({ queryKey: ['slots-day', d], queryFn: () => api.slotsForDay(d) })),
  });
  const [picked, setPicked] = useState<number | null>(null);

  const todayIdx = today.data ? weekdayOf(today.data.check_date) : null;
  const selected = picked ?? (todayIdx !== null && todayIdx <= 5 ? todayIdx : 0);

  const weekPending = week.some((q) => q.isPending);
  const weekError = week.find((q) => q.isError);
  const all: Slot[] = week.flatMap((q) => q.data ?? []);
  const rows = Array.from(new Map(all.map((s) => [`${s.start_time}|${s.end_time}`, s])).values())
    .sort((a, b) => toMinutes(a.start_time) - toMinutes(b.start_time))
    .map((s) => ({ start: s.start_time, end: s.end_time }));
  const daySlots = (week[selected]?.data ?? []).slice().sort((a, b) => toMinutes(a.start_time) - toMinutes(b.start_time));

  return (
    <section className="mx-auto w-full max-w-6xl space-y-4 p-3 sm:p-6" aria-labelledby="sched-h">
      <h1 id="sched-h" className="text-xl font-extrabold text-slate-900 dark:text-white">
        My schedule
      </h1>

      <div className="rounded-2xl bg-blue-700 p-4 text-white" aria-live="polite">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-100">Up next</div>
        {next.isPending ? (
          <div className="mt-2 h-6 w-2/3 animate-pulse rounded bg-blue-500" aria-label="Loading next class" />
        ) : next.isError ? (
          <p className="mt-1 text-sm">
            {errorMessage(next.error)}{' '}
            <button type="button" onClick={() => next.refetch()} className="font-semibold underline">
              Retry
            </button>
          </p>
        ) : next.data ? (
          <div className="mt-1">
            <p className="text-lg font-bold">{next.data.subject.name}</p>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-blue-50">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-4 w-4" aria-hidden="true" />
                {next.data.day_name}, {formatTime(next.data.start_time)} – {formatTime(next.data.end_time)}
              </span>
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-4 w-4" aria-hidden="true" />
                {next.data.room ? `Room ${next.data.room}` : 'Room to be announced'}
              </span>
              {next.data.needs_review && <span className="rounded bg-amber-200 px-1.5 py-0.5 text-xs font-bold text-amber-900">To be confirmed</span>}
            </p>
          </div>
        ) : (
          <p className="mt-1 text-sm">
            {today.data?.suppressed ? 'No regular classes today (holiday or event).' : 'No more classes today.'}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700 dark:text-slate-200" aria-label="Legend" role="group">
        <span className="inline-flex items-center gap-1"><span className="h-3 w-3 rounded border border-blue-300 bg-blue-100" aria-hidden="true" /> Lecture</span>
        <span className="inline-flex items-center gap-1"><span className="h-3 w-3 rounded border border-violet-300 bg-violet-100" aria-hidden="true" /> Lab</span>
        <span className="inline-flex items-center gap-1"><span className="h-3 w-3 rounded border border-dashed border-amber-500" aria-hidden="true" /> To be confirmed by the department</span>
      </div>

      {weekError ? (
        <ErrorPanel message={errorMessage(weekError.error)} onRetry={() => week.forEach((q) => q.isError && q.refetch())} />
      ) : weekPending ? (
        <div className="grid gap-3 sm:grid-cols-2" aria-busy="true" aria-label="Loading timetable">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />
          ))}
        </div>
      ) : (
        <>
          {/* Mobile: one day at a time */}
          <div className="md:hidden">
            <div className="flex gap-1.5 overflow-x-auto pb-2" role="group" aria-label="Choose a day">
              {DAYS.map((d) => (
                <button
                  key={d}
                  type="button"
                  aria-pressed={selected === d}
                  onClick={() => setPicked(d)}
                  className={`shrink-0 rounded-xl px-3 py-2 text-xs font-semibold ${
                    selected === d ? 'bg-blue-700 text-white' : 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100'
                  }`}
                >
                  {DAY_NAMES[d].slice(0, 3)}
                  {todayIdx === d && <span className="sr-only"> (today)</span>}
                  {todayIdx === d && <span aria-hidden="true"> •</span>}
                </button>
              ))}
            </div>
            {daySlots.length === 0 ? (
              <p className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                No classes on {DAY_NAMES[selected]}
              </p>
            ) : (
              <ul className="space-y-2">
                {daySlots.map((s) => (
                  <li key={s.id}>
                    <p className="mb-0.5 text-xs font-semibold text-slate-700 dark:text-slate-200">
                      {formatTime(s.start_time)} – {formatTime(s.end_time)}
                    </p>
                    <SlotCard slot={s} showNames />
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Desktop: weekly grid */}
          <div className="hidden overflow-x-auto md:block">
            {rows.length === 0 ? (
              <p className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                No classes found in your timetable.
              </p>
            ) : (
              <table className="w-full min-w-[900px] border-separate border-spacing-1 text-left">
                <caption className="sr-only">Weekly timetable, Monday to Saturday</caption>
                <thead>
                  <tr>
                    <th scope="col" className="w-28 p-2 text-xs text-slate-700 dark:text-slate-200">Time</th>
                    {DAYS.map((d) => (
                      <th key={d} scope="col" className={`p-2 text-xs ${todayIdx === d ? 'rounded-lg bg-blue-100 text-blue-900' : 'text-slate-700 dark:text-slate-200'}`}>
                        {DAY_NAMES[d]}
                        {todayIdx === d && ' (today)'}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.start}|${r.end}`}>
                      <th scope="row" className="p-2 text-xs font-semibold text-slate-800 dark:text-slate-100">
                        {formatTime(r.start)} – {formatTime(r.end)}
                      </th>
                      {DAYS.map((d) => (
                        <td key={d} className="align-top">
                          <div className="space-y-1">
                            {all
                              .filter((s) => s.day_of_week === d && s.start_time === r.start && s.end_time === r.end)
                              .map((s) => (
                                <SlotCard key={s.id} slot={s} showNames={false} />
                              ))}
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </section>
  );
}
