import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { tokens } from '../services/session';
import { mockFetch } from '../test/mockFetch';
import { renderWithProviders } from '../test/render';
import { admin, student } from '../test/fixtures';
import { RichText } from './RichText';
import { render } from '@testing-library/react';

describe('role guards', () => {
  it('shows the sign-in screen when there is no session', async () => {
    mockFetch({});
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy();
  });

  it('students never see the Admin tab', async () => {
    tokens.set('a', 'r');
    mockFetch({ 'GET /auth/me': { body: student } });
    render(<App />);
    await screen.findByRole('navigation', { name: 'Main' });
    expect(screen.queryByRole('button', { name: /admin/i })).toBeNull();
    expect(screen.getByRole('button', { name: /ai chat/i })).toBeTruthy();
  });

  it('admins see the Admin tab and an explanation instead of chat', async () => {
    tokens.set('a', 'r');
    mockFetch({
      'GET /auth/me': { body: admin },
      'GET /admin/review-queue': { body: { total: 0, items: [] } },
      'GET /admin/faculty': { body: [] },
    });
    render(<App />);
    expect(await screen.findByRole('button', { name: /admin/i })).toBeTruthy();
    await userEvent.setup().click(screen.getByRole('button', { name: /ai chat/i }));
    expect(await screen.findByText(/Chat is for students and faculty/)).toBeTruthy();
  });
});

describe('RichText', () => {
  it('renders bold and bullets but never HTML', () => {
    const { container } = renderWithProviders(<RichText text={'<b onclick="x">hi</b> **Bold**\n* one\n* two'} />);
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByText('Bold').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });
});

