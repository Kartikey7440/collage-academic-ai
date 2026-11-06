import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ScheduleTab from './ScheduleTab';
import AdminTab from './AdminTab';
import { tokens } from '../services/session';
import { callsTo, mockFetch, type Route } from '../test/mockFetch';
import { renderWithProviders } from '../test/render';
import { admin, reviewItem, slot, student } from '../test/fixtures';

function scheduleRoutes(over: Record<string, Route> = {}): Record<string, Route> {
  const days: Record<string, Route> = {};
  for (let d = 0; d <= 5; d++) days[`GET /timetable/day/${d}`] = { body: [] };
  return {
    'GET /auth/me': { body: student },
    'GET /timetable/suppressed': { body: { suppressed: false, check_date: '2026-11-02' } },
    'GET /timetable/next-class': { body: null },
    ...days,
    ...over,
  };
}

describe('schedule', () => {
  it('renders lab, batch and unconfirmed labels and the server-driven "Up next"', async () => {
    tokens.set('a', 'r');
    mockFetch(
      scheduleRoutes({
        'GET /timetable/next-class': { body: slot({ subject: { id: 9, code: 'AI-309', name: 'Machine Learning', is_lab: false } }) },
        'GET /timetable/day/0': {
          body: [
            slot({ id: 1, subject: { id: 2, code: 'AI-307', name: 'Python Lab', is_lab: true }, batch: 'A' }),
            slot({ id: 2, start_time: '11:00:00', end_time: '12:00:00', needs_review: true }),
          ],
        },
      }),
    );
    renderWithProviders(<ScheduleTab />);
    const upNext = (await screen.findByText('Up next')).parentElement as HTMLElement;
    expect(await within(upNext).findByText('Machine Learning')).toBeTruthy();
    expect((await screen.findAllByText('Batch A')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('To be confirmed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Lab').length).toBeGreaterThan(1);
  });

  it('shows empty states when nothing is scheduled', async () => {
    tokens.set('a', 'r');
    mockFetch(scheduleRoutes());
    renderWithProviders(<ScheduleTab />);
    expect(await screen.findByText('No classes on Monday')).toBeTruthy();
    expect(screen.getByText('No more classes today.')).toBeTruthy();
  });

  it('shows an error with Retry and refetches when it is pressed', async () => {
    tokens.set('a', 'r');
    const f = mockFetch(scheduleRoutes({ 'GET /timetable/day/0': { status: 500, body: {} } }));
    renderWithProviders(<ScheduleTab />);
    const retry = await screen.findByRole('button', { name: 'Retry' });
    const before = callsTo(f, 'GET', '/timetable/day/0');
    await userEvent.setup().click(retry);
    await screen.findByRole('alert');
    expect(callsTo(f, 'GET', '/timetable/day/0')).toBeGreaterThan(before);
  });
});

describe('admin', () => {
  const facultyRoute = { 'GET /admin/faculty': { body: [{ code: 'SO', name: 'Satyam Omar' }] } };

  async function openRow() {
    renderWithProviders(<AdminTab />);
    await screen.findByText(/AI-307: Python Lab/);
  }

  it('rolls back the optimistic removal and shows the server 422 next to the row', async () => {
    tokens.set('a', 'r');
    const f = mockFetch({
      'GET /auth/me': { body: admin },
      ...facultyRoute,
      'GET /admin/review-queue': { body: { total: 1, items: [reviewItem] } },
      'PATCH /admin/slots/7': { status: 422, body: { detail: 'Unknown faculty code(s): ZZ' } },
    });
    await openRow();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /save & confirm/i }));
    expect(callsTo(f, 'PATCH', '/admin/slots/7')).toBe(0); // confirmation first
    await user.click(screen.getByRole('button', { name: /yes, save/i }));
    expect(await screen.findByText('Unknown faculty code(s): ZZ')).toBeTruthy();
    expect(screen.getByText(/AI-307: Python Lab/)).toBeTruthy(); // row restored
  });

  it('removes the row after a successful save', async () => {
    tokens.set('a', 'r');
    let saved = false;
    mockFetch({
      'GET /auth/me': { body: admin },
      ...facultyRoute,
      'GET /admin/review-queue': () => ({ body: saved ? { total: 0, items: [] } : { total: 1, items: [reviewItem] } }),
      'PATCH /admin/slots/7': () => {
        saved = true;
        return { body: { ...reviewItem, needs_review: false } };
      },
    });
    await openRow();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /save & confirm/i }));
    await user.click(screen.getByRole('button', { name: /yes, save/i }));
    expect(await screen.findByText('Nothing to review.')).toBeTruthy();
  });

  it('rejects unknown faculty codes before calling the server', async () => {
    tokens.set('a', 'r');
    const f = mockFetch({
      'GET /auth/me': { body: admin },
      ...facultyRoute,
      'GET /admin/review-queue': { body: { total: 1, items: [reviewItem] } },
    });
    await openRow();
    await screen.findByDisplayValue('SO');
    const user = userEvent.setup();
    const input = screen.getByLabelText(/Faculty codes for/);
    await user.clear(input);
    await user.type(input, 'QQ');
    await user.click(screen.getByRole('button', { name: /save & confirm/i }));
    await user.click(screen.getByRole('button', { name: /yes, save/i }));
    expect(await screen.findByText('Unknown faculty code(s): QQ')).toBeTruthy();
    expect(callsTo(f, 'PATCH', '/admin/slots/7')).toBe(0);
  });
});

