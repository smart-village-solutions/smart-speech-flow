import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { StaffContentSettled } from '@/test/ContentSettled';
import { staffContentBodyWith } from '@/test/contentFixtures';
import { staffContentHandler, staffContentUnavailable } from '@/test/handlers';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
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

/** Renders the list and waits until its staff content has arrived or failed. */
const renderList = async (sessions = SESSIONS, isError = false) => {
  renderWithProviders(
    <>
      <AdminSessionList sessions={sessions} isError={isError} onEnter={vi.fn()} />
      <StaffContentSettled />
    </>,
    { locale: 'de' }
  );
  await screen.findByTestId('staff-content-settled');
};

const startedCell = (id: string) =>
  screen.getByRole('button', { name: `Gespräch ${id} fortsetzen` }).children[1];

describe('AdminSessionList', () => {
  it('titles the card', async () => {
    await renderList();
    expect(await screen.findByText('Vergangene Gespräche')).toBeInTheDocument();
  });

  it('keeps the order it is given', async () => {
    await renderList();

    await screen.findByText('Arabisch');
    const languages = screen
      .getAllByText(/Arabisch|Türkisch|Sprache offen/)
      .map((node) => node.textContent);
    expect(languages[0]).toBe('Arabisch');
    expect(languages[1]).toBe('Türkisch');
  });

  it('offers re-entry only for the session that is still open', async () => {
    await renderList();

    await screen.findByText('Arabisch');
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Gespräch AR000001 fortsetzen' })).toBeInTheDocument();
  });

  it('says the language is unknown when the gateway sends a code we cannot name', async () => {
    await renderList();
    expect(await screen.findByText('Sprache offen')).toBeInTheDocument();
  });

  it('says the list is empty rather than showing nothing', async () => {
    await renderList([]);
    expect(await screen.findByText('Noch keine Gespräche.')).toBeInTheDocument();
  });

  // An empty list on a failed request would claim there are no sessions, which
  // is a different and much worse statement than "we could not ask".
  it('says the request failed rather than claiming there are no sessions', async () => {
    await renderList([], true);

    expect(
      await screen.findByText('Die Gesprächsliste konnte nicht geladen werden.')
    ).toBeInTheDocument();
    expect(screen.queryByText('Noch keine Gespräche.')).not.toBeInTheDocument();
  });

  it("prefers Studio's staff name for a language", async () => {
    server.use(
      staffContentHandler(staffContentBodyWith({ guestLanguageNames: { ar: 'Arabisch (Studio)' } }))
    );
    await renderList();

    expect(screen.getByText('Arabisch (Studio)')).toBeInTheDocument();
    expect(screen.getByText('Türkisch')).toBeInTheDocument();
  });

  it('still names languages in German when the staff route answers 503', async () => {
    server.use(staffContentUnavailable());
    await renderList();

    expect(screen.getByText('Arabisch')).toBeInTheDocument();
    expect(screen.queryByText('العربية')).not.toBeInTheDocument();
  });

  it.each([
    ['Europe/Berlin', /13:20/],
    ['America/New_York', /07:20/],
  ])('shows start times in the tenant zone %s', async (timeZone, time) => {
    server.use(staffContentHandler(staffContentBodyWith({ timeZone })));
    await renderList();

    expect(startedCell('AR000001')).toHaveTextContent(time);
  });
});
