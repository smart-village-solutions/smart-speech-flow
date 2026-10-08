import { http, HttpResponse } from 'msw';
import { screen, waitForElementToBeRemoved, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes, useParams } from 'react-router-dom';
import { server } from '@/test/setup';
import { useQuery } from '@tanstack/react-query';
import {
  GUEST_LANGUAGES_ROUTE,
  SESSION_ID,
  guestContentHandler,
  guestLanguagesHandler,
} from '@/test/handlers';
import { STUDIO_ICON_URL, guestContentBody, guestLanguagesBodyWith } from '@/test/contentFixtures';
import { contentKeys } from '@/features/content/contentQuery';
import type { GuestContent } from '@/domain/content/content.types';
import { renderWithProviders } from '@/test/renderWithProviders';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';

function tree(consent: React.ReactNode = <p>consent screen</p>) {
  return (
    <Routes>
      <Route path="/s/:sessionId/language" element={<LanguageSelectScreen />} />
      <Route path="/s/:sessionId/info/:languageCode" element={consent} />
    </Routes>
  );
}

/** Reads the consent screen's cache entry without ever fetching it. */
function CachedGuestContent() {
  const { languageCode = '' } = useParams<{ languageCode: string }>();
  const query = useQuery<GuestContent>({
    queryKey: contentKeys.guest(SESSION_ID, languageCode),
    enabled: false,
  });
  if (query.data === undefined) return <p>nothing cached</p>;
  return <p>{query.data.provided ? 'cached studio content' : 'cached bundled content'}</p>;
}

const route = '/s/A1B2C3D4/language';

describe('LanguageSelectScreen', () => {
  it('positions content below the header with the shared content offset', async () => {
    renderWithProviders(tree(), { route });
    await screen.findByRole('button', { name: /العربية/ });

    expect(
      screen.getByRole('heading', { name: 'Choose your language' }).parentElement?.parentElement
    ).toHaveClass('pt-content-top');
  });

  it("lists the session's nine guest languages, never German, without the supported-languages route", async () => {
    server.use(
      http.get('*/api/languages/supported', () => new HttpResponse(null, { status: 500 }))
    );

    renderWithProviders(tree(), { route });

    const arabic = await screen.findByRole('button', { name: /العربية/ });
    const list = arabic.closest('ul') as HTMLElement;
    expect(within(list).getAllByRole('button')).toHaveLength(9);
    expect(screen.queryByRole('button', { name: /Deutsch/ })).not.toBeInTheDocument();
  });

  it("shows Studio's name and icon where Studio provides the language, bundled ones elsewhere", async () => {
    server.use(
      guestLanguagesHandler(
        guestLanguagesBodyWith({
          en: {
            nativeName: 'English (Studio)',
            icon: { url: STUDIO_ICON_URL, alternativeText: 'Flag EN' },
          },
          ar: { nativeName: 'عربي', icon: null },
        })
      )
    );

    renderWithProviders(tree(), { route });

    const english = await screen.findByRole('button', { name: /English \(Studio\)/ });
    expect(within(english).getByText('English')).toBeInTheDocument();
    expect(within(english).getByRole('img')).toHaveAttribute('src', STUDIO_ICON_URL);

    const arabic = screen.getByRole('button', { name: /عربي/ });
    expect(within(arabic).getByText('Arabic')).toBeInTheDocument();
    expect(within(arabic).getByRole('img')).toHaveAttribute('src', '/flags/sa.png');

    const turkish = screen.getByRole('button', { name: /Türkçe/ });
    expect(within(turkish).getByRole('img')).toHaveAttribute('src', '/flags/tr.png');
  });

  it('shows the English name as a subtitle only when it differs from the native name', async () => {
    renderWithProviders(tree(), { route });

    expect(await screen.findByText('Arabic')).toBeInTheDocument();
    // English is its own English name, so it appears once, not twice.
    expect(screen.getAllByText('English')).toHaveLength(1);
  });

  it('opens the consent screen for the chosen language with its content prefetched', async () => {
    renderWithProviders(tree(<CachedGuestContent />), { route });
    await userEvent.click(await screen.findByRole('button', { name: /Türkçe/ }));

    expect(await screen.findByText('cached bundled content')).toBeInTheDocument();
  });

  it('shows placeholder rows while the list loads', async () => {
    let answer = () => {};
    const answered = new Promise<void>((resolve) => {
      answer = resolve;
    });
    server.use(
      http.get(GUEST_LANGUAGES_ROUTE, async () => {
        await answered;
        return HttpResponse.json({ languages: [] });
      })
    );

    renderWithProviders(tree(), { route });

    try {
      expect(screen.getByRole('status', { name: 'Choose your language' })).toBeInTheDocument();
    } finally {
      answer();
    }
    await waitForElementToBeRemoved(() =>
      screen.queryByRole('status', { name: 'Choose your language' })
    );
  });

  it('offers a retry when the list cannot be loaded', async () => {
    server.use(http.get(GUEST_LANGUAGES_ROUTE, () => new HttpResponse(null, { status: 500 })));

    renderWithProviders(tree(), { route });

    expect(await screen.findByText('The language list could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it("loads the chosen language's guest content into the cache the consent screen reads", async () => {
    const requested: string[] = [];
    server.use(
      guestContentHandler((language) => {
        requested.push(language);
        return HttpResponse.json(guestContentBody(language));
      })
    );

    renderWithProviders(tree(<CachedGuestContent />), { route });

    await userEvent.click(await screen.findByRole('button', { name: /English/ }));

    expect(await screen.findByText('cached studio content')).toBeInTheDocument();
    expect(requested).toEqual(['en']);
  });
});
