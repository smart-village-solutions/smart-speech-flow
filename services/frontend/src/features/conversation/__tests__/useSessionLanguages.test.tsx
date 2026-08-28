import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { act, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { useSessionLanguages } from '@/features/conversation/useSessionLanguages';
import type { ClientRole } from '@/core/roles';

const arabicSession = () =>
  server.use(
    http.get('*/api/session/:id', ({ params }) =>
      HttpResponse.json({
        id: params.id,
        customer_language: 'ar',
        admin_language: 'de',
        status: 'active',
        created_at: '2026-08-26T10:00:00+00:00',
        message_count: 0,
        admin_connected: true,
        customer_connected: true,
      })
    )
  );

function Probe({ role }: Readonly<{ role: ClientRole }>) {
  const { source, target, customerLanguage } = useSessionLanguages('A1B2C3D4', role);
  return (
    <p>
      {source}→{target} ({customerLanguage}) [{document.documentElement.lang}]
    </p>
  );
}

describe('useSessionLanguages', () => {
  it('sends the customer from their language into German', async () => {
    arabicSession();
    renderWithProviders(<Probe role="customer" />, { locale: 'en' });
    expect(await screen.findByText(/ar→de \(ar\)/)).toBeInTheDocument();
  });

  it('sends the admin from German into the customer language', async () => {
    arabicSession();
    renderWithProviders(<Probe role="admin" />, { locale: 'de' });
    expect(await screen.findByText(/de→ar \(ar\)/)).toBeInTheDocument();
  });

  // The customer screen adopts the customer's language. The admin screen must
  // not: staff copy is German, and an admin UI in Arabic is a bug, not a
  // courtesy.
  it('leaves the admin screen in German', async () => {
    arabicSession();
    renderWithProviders(<Probe role="admin" />, { locale: 'de' });

    await screen.findByText(/de→ar/);
    // Adopting a locale takes two commits after the session answers: one to
    // call `setLocale`, one for the provider to write the attribute. Settle
    // them, or this passes for a screen that was about to turn Arabic.
    await act(async () => undefined);

    expect(document.documentElement.lang).toBe('de');
  });

  it('puts the customer screen into the customer language', async () => {
    arabicSession();
    renderWithProviders(<Probe role="customer" />, { locale: 'de' });

    // The locale is adopted one commit after the session answers, so the
    // attribute is what to wait on — the text appears first.
    await waitFor(() => expect(document.documentElement.lang).toBe('ar'));
  });
});
