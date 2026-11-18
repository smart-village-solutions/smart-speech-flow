import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { ConversationUsageCard } from '../ConversationUsageCard';

const report = {
  window_start: '2026-10-19T08:00:00Z',
  window_end: '2026-11-18T08:00:00Z',
  coverage_start: '2026-11-01T08:00:00Z',
  complete: false,
  personal: { total_seconds: 7200, by_language: { ar: 4200, uk: 3000 } },
  organisation: { total_seconds: 50400, by_language: { ar: 30000, uk: 20400 } },
  server: { total_seconds: 255000, by_language: { ar: 180000, uk: 75000 } },
};

function respond(body = report) {
  server.use(http.get('*/api/admin/usage', () => HttpResponse.json(body)));
}

describe('ConversationUsageCard', () => {
  it('shows loading without inventing zero totals while the response is pending', async () => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('*/api/admin/usage', async () => {
        await pending;
        return HttpResponse.json(report);
      })
    );
    renderWithProviders(<ConversationUsageCard />, { locale: 'de' });
    try {
      expect(await screen.findByRole('status')).toHaveTextContent(
        'Gesprächsminuten werden geladen'
      );
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    } finally {
      release();
    }
    expect(await screen.findByText('120 Min.')).toBeInTheDocument();
  });

  it('shows all three totals and reveals language-only rows with one disclosure', async () => {
    respond();
    renderWithProviders(<ConversationUsageCard />, { locale: 'de' });
    expect(await screen.findByText('120 Min.')).toBeInTheDocument();
    expect(screen.getByText('840 Min.')).toBeInTheDocument();
    expect(screen.getByText('4.250 Min.')).toBeInTheDocument();
    const toggle = screen.getByRole('button', { name: 'Nach Sprache anzeigen' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const table = screen.getByRole('table', { name: /Gesprächsminuten/ });
    expect(within(table).getByText('Arabisch')).toBeInTheDocument();
    expect(within(table).getByText('Ukrainisch')).toBeInTheDocument();
    expect(table).not.toHaveTextContent('Deutsch');
    expect(within(table).getByText('70')).toBeInTheDocument();
    expect(screen.getByText(/Vollständige Erfassung seit/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Sprachen ausblenden' }));
    expect(screen.queryByText('Arabisch')).not.toBeInTheDocument();
  });

  it('shows unavailable instead of zero on a failed request', async () => {
    server.use(http.get('*/api/admin/usage', () => new HttpResponse(null, { status: 503 })));
    renderWithProviders(<ConversationUsageCard />, { locale: 'de' });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Gesprächsminuten derzeit nicht abrufbar'
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not show incomplete coverage for a complete window', async () => {
    respond({ ...report, complete: true, coverage_start: '2026-09-01T08:00:00Z' });
    renderWithProviders(<ConversationUsageCard />, { locale: 'de' });
    await screen.findByText('120 Min.');
    expect(screen.queryByText(/Vollständige Erfassung seit/)).not.toBeInTheDocument();
  });

  it('rejects malformed totals instead of rendering misleading numbers', async () => {
    server.use(
      http.get('*/api/admin/usage', () =>
        HttpResponse.json({ ...report, server: { total_seconds: -1 } })
      )
    );
    renderWithProviders(<ConversationUsageCard />, { locale: 'de' });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
