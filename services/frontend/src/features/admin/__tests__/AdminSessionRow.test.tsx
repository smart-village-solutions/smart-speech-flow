import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminSessionRow } from '@/features/admin/AdminSessionRow';
import type { AdminSession } from '@/domain/admin/admin.types';

const ARABIC = { code: 'ar', native: 'العربية', english: 'Arabic' };

/** Local wall-clock, so the rendered time does not depend on the runner's TZ. */
const at = (day: number, hour: number, minute: number) => new Date(2026, 7, day, hour, minute);

const session = (over: Partial<AdminSession> = {}): AdminSession => ({
  id: 'AR000001',
  status: 'completed',
  customerLanguage: 'ar',
  createdAt: at(26, 9, 0).toISOString(),
  terminatedAt: at(26, 9, 14).toISOString(),
  ...over,
});

const renderRow = (over: Partial<AdminSession> = {}, onEnter = vi.fn()) => {
  renderWithProviders(
    <AdminSessionRow
      session={session(over)}
      language={ARABIC}
      now={at(26, 18, 0)}
      onEnter={onEnter}
    />,
    { locale: 'de' }
  );
  return onEnter;
};

describe('AdminSessionRow', () => {
  it('names the language in its own script', async () => {
    renderRow();
    expect(await screen.findByText('العربية')).toBeInTheDocument();
  });

  it('says the language is still open when the customer never chose one', async () => {
    renderWithProviders(
      <AdminSessionRow
        session={session({ customerLanguage: null, status: 'open', terminatedAt: null })}
        language={null}
        now={at(26, 18, 0)}
        onEnter={vi.fn()}
      />,
      { locale: 'de' }
    );
    expect(await screen.findByText('Sprache offen')).toBeInTheDocument();
  });

  it('shows the start time as a day and a clock time', async () => {
    renderRow();
    expect(await screen.findByText('Heute, 09:00')).toBeInTheDocument();
  });

  it('shows the duration in whole minutes', async () => {
    renderRow();
    expect(await screen.findByText('14 Min.')).toBeInTheDocument();
  });

  it('measures an open session against now rather than leaving it blank', async () => {
    renderRow({ status: 'connected', terminatedAt: null, createdAt: at(26, 17, 30).toISOString() });
    expect(await screen.findByText('30 Min.')).toBeInTheDocument();
  });

  it('is inert when the session is completed', async () => {
    renderRow();
    expect(await screen.findByText('abgeschlossen')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('is a button naming the session when it can be re-entered', async () => {
    const onEnter = renderRow({ status: 'connected', terminatedAt: null });

    const row = await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' });
    await userEvent.click(row);

    expect(onEnter).toHaveBeenCalledWith('AR000001');
  });

  it('distinguishes an open session from a connected one', async () => {
    renderRow({ status: 'open', terminatedAt: null });
    expect(await screen.findByText('offen')).toBeInTheDocument();
  });
});
