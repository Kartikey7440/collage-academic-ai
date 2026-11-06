# Frontend progress (frontend/ only)

## Step 0 - gaps found (read-only, no code changed)
1. API client calls wrong paths/shapes: `/timetable/day/{name}` (backend wants int 0-6), `/timetable/next` (real: `/timetable/next-class`), expects `{slots}` wrappers; backend returns plain arrays / nullable.
2. Chat reads `data.response`; backend returns `reply` (+ `fallback`, `elapsed_ms`, `assistant_time`); `history` never sent.
3. Calendar uses `category`; backend field is `event_type`. Admin queue uses `count`; backend returns `total`.
4. Schedule picks "today" and "up next" from the browser clock; must come from the server.
5. Tokens persisted in localStorage; no clear-on-signout of cached data; no "Your session expired" flow; no timeout, typed errors, or response validation.
6. No role guards: admins see Chat (403), no explanation; Admin tab hidden only by tab button.
7. No ErrorBoundary, toasts, offline banner, 404; AuthModal ships hard-coded demo credentials.
8. No tests, no a11y lint, no lazy loading, no query cache; chat has no safe formatting, retry, persistence, or counter.

## Backend requests
1. Include `server_time` (ISO timestamp honoring `DEMO_NOW`) on `GET /timetable/next-class` or `GET /timetable/suppressed` so Schedule/Calendar can display the exact server clock time in addition to `check_date`.
2. Add a single `GET /timetable/week` endpoint returning Mon-Sat slots in one payload to replace the 6 parallel `/timetable/day/{0..5}` requests.

## Step 1 - DONE (reliability & auth)
Files: services/{api,errors,schemas,session}.ts, types/index.ts, queryClient.ts, context/{AuthContext,ToastContext}.tsx, components/{ErrorBoundary,OfflineBanner,NotFound,LoginScreen,Navbar,CalendarTab}.tsx, lib/format.ts, App.tsx, index.css. Removed AuthModal (it shipped hard-coded demo credentials) and App.css. Chat/Schedule/Admin are temporary minimal versions, replaced in steps 2-4. Packages added: @tanstack/react-query, zod, vitest, @testing-library/react, @testing-library/user-event, jsdom.
Also fixed: wrong API paths/shapes (see Step 0), browser-clock IST chip removed from the navbar, tokens now sessionStorage only. CalendarTab no longer shows hard-coded policy cards (text was not taken from the PDF); it points to the AI Chat instead.
Results: `npm.cmd run build` OK (862 ms); `npm.cmd run lint` 0 errors, 3 warnings (react/only-export-components, fixed in step 5); `npx.cmd tsc --noEmit` exit 0.

## Step 2 - DONE (chat)
Files: components/ChatTab.tsx (rewritten), components/RichText.tsx, lib/chatStore.ts. Admin gets an explanation instead of chat. Safe renderer (no dangerouslySetInnerHTML; line breaks, **bold**, "* " bullets). Typing indicator, Enter/Shift+Enter, 500-char counter, blank blocked, fallback badge, seconds, assistant clock chip (from assistant_time), error bubble + Retry, last 50 messages per user in sessionStorage (cleared on sign out), copy, suggestion chips, scroll-lock aware auto-scroll, role="log" aria-live.
Results: build OK (864 ms), lint 0 errors / 3 warnings (same as step 1), tsc exit 0.

## Step 3 - DONE (schedule)
Files: components/ScheduleTab.tsx (rewritten). Weekly grid (md+), day list with day pills (mobile), Lab / "To be confirmed" (needs_review) / Batch labels + legend, "Up next" from GET /timetable/next-class, server "today" from GET /timetable/suppressed (check_date, honours demo clock; also shows holiday text), skeletons, empty states, errors with Retry, TanStack Query (staleTime 60 s, refetch on focus via queryClient defaults).
Results: build OK (910 ms), lint 0 errors / 3 warnings, tsc exit 0.

## Step 4 - DONE (admin)
Files: components/AdminTab.tsx (rewritten). Card list with per-row form: inline two-step confirm ("Save & confirm" -> "Yes, save"/Cancel, Esc cancels), optimistic removal with rollback (TanStack mutation onMutate/onError), server 422 message shown in the row (role="alert"), client-side unknown-code check against GET /admin/faculty, datalist suggestions, labelled inputs, "Saving N change(s)" status line. Kept search/branch/semester filters and bulk "Confirm all shown" (now with a Yes/No confirmation, sequential, per-row error on failure).
Note: because the row is removed optimistically, the per-row loading state is the global "Saving N" status line (the row itself is gone until a rollback).
Results: build OK (944 ms), lint 0 errors / 3 warnings, tsc exit 0.


## Step 5 - DONE (code quality, accessibility & unit tests)
Files: tsconfig.app.json (`strict: true`), .oxlintrc.json (`jsx-a11y` enabled), vite.config.ts (vitest jsdom config), package.json (`test` script), context/{auth-context,toast-context}.ts, hooks/useOnline.ts, test/{setup,mockFetch,render,fixtures}.ts(x), services/api.test.ts, components/{guards,chat,schedule-admin}.test.tsx. Tabs lazy-loaded in App.tsx.
Results: `npm.cmd run build` OK (854 ms; main JS 252.84 kB / 78.68 kB gzip, CSS 29.05 kB / 6.57 kB gzip); `npm.cmd run lint` 0 warnings and 0 errors (34 files); `npx.cmd tsc --noEmit` exit 0; `npm.cmd test` 4 passed (26 tests).

## Step 6 - DONE (deployment files - written, not run)
Files: Dockerfile, nginx.conf, .env.example, README.md ("Deploying the frontend" section).
Results: `npm.cmd run build` OK; `npm.cmd run lint` 0 warnings and 0 errors; `npx.cmd tsc --noEmit` exit 0; `npm.cmd test` 26 passed.
