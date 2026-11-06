import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCheck, Loader2, RefreshCw, Search } from 'lucide-react';
import { api } from '../services/api';
import { errorMessage } from '../services/errors';
import { useToast } from '../context/toast-context';
import { formatTime } from '../lib/format';
import type { ReviewItem, ReviewQueue } from '../types';

const QUEUE_KEY = ['review-queue'] as const;

interface Edit {
  room: string;
  faculty: string;
}

const parseCodes = (s: string): string[] =>
  Array.from(new Set(s.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean)));

const defaultEdit = (i: ReviewItem): Edit => ({ room: i.room ?? '', faculty: i.faculty.map((f) => f.code).join(', ') });

interface RowProps {
  item: ReviewItem;
  edit: Edit;
  error?: string;
  onChange: (e: Edit) => void;
  onSave: () => void;
}

function Row({ item, edit, error, onChange, onSave }: RowProps) {
  const [confirming, setConfirming] = useState(false);
  const label = `${item.branch_code ?? ''} ${item.day_name} ${formatTime(item.start_time)}`.trim();
  const input = 'w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white';

  const onEsc = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') setConfirming(false);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (confirming) {
      setConfirming(false);
      onSave();
    } else {
      setConfirming(true);
    }
  };

  return (
    <li className="rounded-2xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
      <form onSubmit={submit}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-bold text-blue-900">{item.branch_code ?? '-'}</span>
          <span className="text-xs text-slate-700 dark:text-slate-200">Sem {item.semester ?? '-'}</span>
          <span className="font-semibold text-slate-900 dark:text-white">
            {item.day_name}, {formatTime(item.start_time)} – {formatTime(item.end_time)}
          </span>
          {item.batch && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-900">Batch {item.batch}</span>}
        </div>
        <p className="mt-1 text-sm text-slate-900 dark:text-white">
          {item.subject ? `${item.subject.code}: ${item.subject.name}` : 'No subject'}
        </p>
        {item.raw_cell_text && (
          <p className="mt-1 break-all rounded bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            Original text: {item.raw_cell_text}
          </p>
        )}

        <div className="mt-3 grid gap-3 sm:grid-cols-[8rem_1fr_auto] sm:items-end">
          <div>
            <label htmlFor={`room-${item.id}`} className="mb-1 block text-xs font-semibold text-slate-700 dark:text-slate-200">Room</label>
            <input id={`room-${item.id}`} className={input} value={edit.room} aria-label={`Room for ${label}`} onKeyDown={onEsc} onChange={(e) => { setConfirming(false); onChange({ ...edit, room: e.target.value }); }} />
          </div>
          <div>
            <label htmlFor={`fac-${item.id}`} className="mb-1 block text-xs font-semibold text-slate-700 dark:text-slate-200">
              Faculty codes (comma separated)
            </label>
            <input
              id={`fac-${item.id}`}
              className={input}
              list="faculty-codes"
              placeholder="e.g. SO, SS"
              value={edit.faculty}
              aria-label={`Faculty codes for ${label}`}
              aria-describedby={error ? `err-${item.id}` : undefined}
              aria-invalid={error ? true : undefined}
              onKeyDown={onEsc}
              onChange={(e) => { setConfirming(false); onChange({ ...edit, faculty: e.target.value }); }}
            />
          </div>
          {confirming ? (
            <div className="flex gap-2" role="group" aria-label="Confirm save">
              <button type="submit" className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-800">
                Yes, save
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="rounded-lg border border-slate-400 px-3 py-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
                Cancel
              </button>
            </div>
          ) : (
            <button type="submit" className="rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-800">
              Save &amp; confirm
            </button>
          )}
        </div>
        {confirming && (
          <p className="mt-2 text-xs text-slate-700 dark:text-slate-200">
            This marks the slot as confirmed for students. Press Yes to save, or Esc to cancel.
          </p>
        )}
        {error && (
          <p id={`err-${item.id}`} role="alert" className="mt-2 rounded-lg bg-red-50 px-2 py-1 text-sm font-medium text-red-800 dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}
      </form>
    </li>
  );
}

export default function AdminTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const queue = useQuery({ queryKey: QUEUE_KEY, queryFn: api.reviewQueue });
  const faculty = useQuery({ queryKey: ['faculty-list'], queryFn: api.facultyList });
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(0);
  const [search, setSearch] = useState('');
  const [branch, setBranch] = useState('ALL');
  const [sem, setSem] = useState('ALL');
  const [bulkConfirm, setBulkConfirm] = useState(false);

  const setError = (id: number, msg: string | null) =>
    setErrors((prev) => {
      const next = { ...prev };
      if (msg) next[id] = msg;
      else delete next[id];
      return next;
    });

  const save = useMutation({
    mutationFn: (v: { item: ReviewItem; edit: Edit }) => {
      const room = v.edit.room.trim();
      return api.patchSlot(v.item.id, { faculty_codes: parseCodes(v.edit.faculty), room: room || null, mark_reviewed: true });
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: QUEUE_KEY });
      const previous = qc.getQueryData<ReviewQueue>(QUEUE_KEY);
      qc.setQueryData<ReviewQueue>(QUEUE_KEY, (old) =>
        old ? { total: Math.max(0, old.total - 1), items: old.items.filter((i) => i.id !== v.item.id) } : old,
      );
      setError(v.item.id, null);
      setSaving((n) => n + 1);
      return { previous };
    },
    onError: (e, v, ctx) => {
      if (ctx?.previous) qc.setQueryData(QUEUE_KEY, ctx.previous);
      setError(v.item.id, errorMessage(e));
    },
    onSuccess: (_d, v) => toast.push('success', `Slot #${v.item.id} confirmed.`),
    onSettled: () => {
      setSaving((n) => n - 1);
      void qc.invalidateQueries({ queryKey: QUEUE_KEY });
    },
  });

  const knownCodes = new Set((faculty.data ?? []).map((f) => f.code.toUpperCase()));
  const items = queue.data?.items ?? [];
  const branches = Array.from(new Set(items.map((i) => i.branch_code).filter((b): b is string => !!b))).sort();
  const q = search.trim().toLowerCase();
  const shown = items.filter(
    (i) =>
      (branch === 'ALL' || i.branch_code === branch) &&
      (sem === 'ALL' || String(i.semester) === sem) &&
      (!q ||
        [i.subject?.code, i.subject?.name, i.room, i.raw_cell_text, ...i.faculty.map((f) => f.code)]
          .filter(Boolean)
          .some((s) => String(s).toLowerCase().includes(q))),
  );

  const trySave = (item: ReviewItem) => {
    const edit = edits[item.id] ?? defaultEdit(item);
    const unknown = faculty.data ? parseCodes(edit.faculty).filter((c) => !knownCodes.has(c)) : [];
    if (unknown.length) {
      setError(item.id, `Unknown faculty code(s): ${unknown.join(', ')}`);
      return;
    }
    save.mutate({ item, edit });
  };

  const bulkSave = async () => {
    setBulkConfirm(false);
    for (const item of shown) {
      const edit = edits[item.id] ?? defaultEdit(item);
      try {
        await save.mutateAsync({ item, edit });
      } catch {
        // the row is restored with its own error message; continue with the rest
      }
    }
  };

  const select = 'rounded-xl border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white';

  return (
    <section className="mx-auto w-full max-w-5xl space-y-4 p-3 sm:p-6" aria-labelledby="admin-h">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 id="admin-h" className="text-xl font-extrabold text-slate-900 dark:text-white">
          Timetable review ({queue.data?.total ?? '…'} pending)
        </h1>
        <button type="button" onClick={() => void queue.refetch()} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-400 px-3 py-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
          <RefreshCw className={`h-4 w-4 ${queue.isFetching ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh
        </button>
      </div>

      <p role="status" className="min-h-5 text-sm text-slate-700 dark:text-slate-200">
        {saving > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Saving {saving} change{saving === 1 ? '' : 's'}…
          </span>
        )}
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
          <label htmlFor="admin-search" className="sr-only">Search slots</label>
          <input id="admin-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search slots" className={`${select} pl-8`} />
        </div>
        <label className="sr-only" htmlFor="admin-branch">Branch</label>
        <select id="admin-branch" className={select} value={branch} onChange={(e) => setBranch(e.target.value)}>
          <option value="ALL">All branches</option>
          {branches.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <label className="sr-only" htmlFor="admin-sem">Semester</label>
        <select id="admin-sem" className={select} value={sem} onChange={(e) => setSem(e.target.value)}>
          <option value="ALL">All semesters</option>
          {Array.from(new Set(items.map((i) => i.semester).filter((s): s is number => s !== null))).sort().map((s) => (
            <option key={s} value={String(s)}>Semester {s}</option>
          ))}
        </select>
        <div className="ml-auto">
          {bulkConfirm ? (
            <span className="inline-flex items-center gap-2 text-sm text-slate-800 dark:text-slate-100">
              Confirm {shown.length} slot{shown.length === 1 ? '' : 's'} as shown?
              <button type="button" onClick={() => void bulkSave()} className="rounded-lg bg-emerald-700 px-3 py-1.5 font-semibold text-white">Yes</button>
              <button type="button" onClick={() => setBulkConfirm(false)} className="rounded-lg border border-slate-400 px-3 py-1.5 font-semibold">No</button>
            </span>
          ) : (
            <button type="button" disabled={shown.length === 0} onClick={() => setBulkConfirm(true)} className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
              <CheckCheck className="h-4 w-4" aria-hidden="true" /> Confirm all shown ({shown.length})
            </button>
          )}
        </div>
      </div>

      {queue.isPending ? (
        <div className="space-y-3" aria-busy="true" aria-label="Loading review queue">
          {[1, 2, 3].map((i) => <div key={i} className="h-28 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />)}
        </div>
      ) : queue.isError ? (
        <div role="alert" className="rounded-2xl border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          {errorMessage(queue.error)}{' '}
          <button type="button" onClick={() => void queue.refetch()} className="font-semibold underline">Retry</button>
        </div>
      ) : shown.length === 0 ? (
        <p className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          Nothing to review{items.length > 0 ? ' with these filters' : ''}.
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((item) => (
            <Row
              key={item.id}
              item={item}
              edit={edits[item.id] ?? defaultEdit(item)}
              error={errors[item.id]}
              onChange={(e) => setEdits((prev) => ({ ...prev, [item.id]: e }))}
              onSave={() => trySave(item)}
            />
          ))}
        </ul>
      )}

      <datalist id="faculty-codes">
        {(faculty.data ?? []).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
      </datalist>
    </section>
  );
}
