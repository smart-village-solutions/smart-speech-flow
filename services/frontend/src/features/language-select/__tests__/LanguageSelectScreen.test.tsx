import { http, HttpResponse, delay } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/language" element={<LanguageSelectScreen />} />
      <Route path="/s/:sessionId/info/:languageCode" element={<p>consent screen</p>} />
    </Routes>
  );
}

const route = '/s/A1B2C3D4/language';

describe('LanguageSelectScreen', () => {
  it('lists the gateway languages without the admin default', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByRole('button', { name: /العربية/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Deutsch/ })).not.toBeInTheDocument();
  });

  it('shows the English name as a subtitle only when it differs from the native name', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByText('Arabic')).toBeInTheDocument();
    // English is its own English name, so it appears once, not twice.
    expect(screen.getAllByText('English')).toHaveLength(1);
  });

  it('navigates to the consent screen carrying the chosen language', async () => {
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: /Türkçe/ }));

    expect(await screen.findByText('consent screen')).toBeInTheDocument();
  });

  it('shows placeholder rows while the list loads', async () => {
    server.use(
      http.get('*/api/languages/supported', async () => {
        await delay(50);
        return HttpResponse.json({ languages: {}, admin_default: 'de', popular: [] });
      })
    );

    renderWithProviders(tree(), { route });

    expect(screen.getByRole('status', { name: 'Choose your language' })).toBeInTheDocument();
  });

  it('offers a retry when the list cannot be loaded', async () => {
    server.use(
      http.get('*/api/languages/supported', () => new HttpResponse(null, { status: 500 }))
    );

    renderWithProviders(tree(), { route });

    expect(await screen.findByText('The language list could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
