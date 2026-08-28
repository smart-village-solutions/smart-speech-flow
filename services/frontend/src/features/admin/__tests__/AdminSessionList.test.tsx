import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminSessionList } from '@/features/admin/AdminSessionList';
import type { AdminSession } from '@/domain/admin/admin.types';

const SESSIONS: AdminSession[] = [
  {
    id: 'AR000001',
    status: 'connected',
    customerLanguage: 'ar',
    createdAt: '2026-08-26T11:20:00+00:00',
    terminatedAt: null,
  },
  {
    id: 'TR000001',
    status: 'completed',
    customerLanguage: 'tr',
    createdAt: '2026-08-26T09:00:00+00:00',
    terminatedAt: '2026-08-26T09:14:00+00:00',
  },
  {
    id: 'XX000001',
    status: 'completed',
    customerLanguage: 'zz',
    createdAt: '2026-08-25T09:00:00+00:00',
    terminatedAt: '2026-08-25T09:30:00+00:00',
  },
];

const renderList = (sessions = SESSIONS, isError = false) =>
  renderWithProviders(
    <AdminSessionList sessions={sessions} isError={isError} onEnter={vi.fn()} />,
    { locale: 'de' }
  );

describe('AdminSessionList', () => {
  it('titles the card', async () => {
    renderList();
    expect(await screen.findByText('Vergangene Gespräche')).toBeInTheDocument();
  });

  it('keeps the order it is given', async () => {
    renderList();

    await screen.findByText('العربية');
    const languages = screen
      .getAllByText(/العربية|Türkçe|Sprache offen/)
      .map((node) => node.textContent);
    expect(languages[0]).toBe('العربية');
    expect(languages[1]).toBe('Türkçe');
  });

  it('offers re-entry only for the session that is still open', async () => {
    renderList();

    await screen.findByText('العربية');
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Gespräch AR000001 fortsetzen' })).toBeInTheDocument();
  });

  it('says the language is unknown when the gateway sends a code we cannot name', async () => {
    renderList();
    expect(await screen.findByText('Sprache offen')).toBeInTheDocument();
  });

  it('says the list is empty rather than showing nothing', async () => {
    renderList([]);
    expect(await screen.findByText('Noch keine Gespräche.')).toBeInTheDocument();
  });

  // An empty list on a failed request would claim there are no sessions, which
  // is a different and much worse statement than "we could not ask".
  it('says the request failed rather than claiming there are no sessions', async () => {
    renderList([], true);

    expect(
      await screen.findByText('Die Gesprächsliste konnte nicht geladen werden.')
    ).toBeInTheDocument();
    expect(screen.queryByText('Noch keine Gespräche.')).not.toBeInTheDocument();
  });
});
