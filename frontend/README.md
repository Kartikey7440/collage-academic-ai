# MITS Smart Campus — Professional Web Application

Production-ready frontend for the MITS Gwalior Academic AI Platform built with **React 19**, **TypeScript**, **Vite**, and **Tailwind CSS**.

---

## 🌟 Features

1. **🤖 Campus AI Assistant (`ChatTab.tsx`)**:
   - Conversational assistant powered by Gemini 2.5 Flash via FastAPI `/api/v1/chat`.
   - Tool execution visibility (`get_timetable_slots`, `get_academic_calendar`).
   - Quick-action suggestion pills, copy-to-clipboard buttons, and auto-scrolling chat history.

2. **📅 Interactive Schedule Matrix (`ScheduleTab.tsx`)**:
   - Day-by-day pills (Monday &ndash; Saturday + jump to Today).
   - "Up Next / Happening Now" real-time banner (`/api/v1/timetable/next`).
   - Filters for Branch (`AI`, `AIR`, `AIDS`, `AIML`, `CSE`), Semester (`3`, `5`), and Batch (`A1`, `A2`).
   - Classroom/Lab room tags, subject codes, and faculty profiles.

3. **🗓️ Academic Calendar & Regulations (`CalendarTab.tsx`)**:
   - Second & Third Year 2026-27 schedule of examinations, breaks, and deadlines.
   - College regulation cards (75% Attendance policy, make-up examination rules, NPTEL/NEC credit transfers).
   - Searchable and categorized filters (`exam`, `break`, `instruction`, `deadline`).

4. **🛡️ Admin Timetable Review Portal (`AdminTab.tsx`)**:
   - Secure review queue for flagged OCR timetable slots.
   - Dynamic branch/semester filters and full-text search.
   - Inline faculty auto-complete (`datalist`) and room editing.
   - Bulk confirmation button for pre-resolved faculty slots.

5. **🎨 Modern UI & Accessibility**:
   - Dark / Light mode with smooth CSS transitions and local storage persistence.
   - Live Indian Standard Time (IST) clock synchronization.
   - Fully responsive design (desktop, tablet, and mobile).

---

## 🚀 Development Setup

### 1. Start the FastAPI Backend (Port 8000)
In the project root:
```powershell
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Start the React Frontend (Port 3000)
Inside `frontend/`:
```powershell
npm.cmd run dev
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser. All `/api` requests are automatically proxied to the backend at `http://127.0.0.1:8000`.

---

## 📦 Production Build & Deployment

### Build Static Bundle:
```powershell
npm.cmd run build
```
The optimized production bundle is generated in `frontend/dist/`.

### Deploying the frontend
1. **Environment variables** (see `.env.example`, names only):
   - `VITE_API_BASE_URL` (build-time, defaults to `/api/v1`)
   - `BACKEND_URL` (runtime Nginx upstream, e.g. `http://backend:8000`)
2. **Docker (multi-stage Node 22 + Nginx 1.27)**:
   - Builds `dist/` via `frontend/Dockerfile` and serves it with `frontend/nginx.conf`.
   - Includes SPA fallback (`try_files $uri $uri/ /index.html`), `/api/` reverse proxy to `${BACKEND_URL}`, and security headers (`Content-Security-Policy` with `script-src 'self'`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`).
3. **Managed Static / PaaS Hosting (Vercel / Netlify / Render)**:
   - Root directory: `frontend`, build command: `npm run build`, publish directory: `dist`, and rewrite `/api/*` to the FastAPI backend.
