import { HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { onlineManager, useQuery } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { useServices } from '@/app/providers/services';
import { readConfig } from '@/app/config/env';
import { server } from '@/test/setup';
import { guestContentHandler, guestLanguagesHandler, holdGuestContent } from '@/test/handlers';
import {
  STUDIO_ENGLISH,
  STUDIO_ICON_URL,
  guestContentBody,
  guestLanguagesBodyWith,
} from '@/test/contentFixtures';
import { GuestContentSettled } from '@/test/ContentSettled';
import { contentKeys } from '@/features/content/contentQuery';
import type { GuestContent } from '@/domain/content/content.types';
import ar from '@/i18n/locales/ar.json';
import en from '@/i18n/locales/en.json';

function tree(live: React.ReactNode = <p>conversation screen</p>, language = 'en') {
  return (
    <>
      <Routes>
        <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
        <Route path="/s/:sessionId/live" element={live} />
      </Routes>
      <GuestContentSettled sessionId="A1B2C3D4" language={language} />
    </>
  );
}

/** Studio's English texts, distinct from the bundled ones. */
function studioEnglish() {
  return guestContentHandler((language) =>
    HttpResponse.json(
      language === 'en'
        ? { ...guestContentBody(language), explanationHtml: STUDIO_ENGLISH.explanationHtml }
        : guestContentBody(language)
    )
  );
}

/** Shows once the consent screen's cache entry holds Studio content, without fetching it. */
function CachedStudioContent() {
  const query = useQuery<GuestContent>({
    queryKey: contentKeys.guest('A1B2C3D4', 'en'),
    enabled: false,
  });
  return query.data?.provided ? <span data-testid="studio-content-cached" hidden /> : null;
}

/** The prose block: the bundled paragraphs or Studio's rendered markup. */
function prose(paragraph: string | RegExp): HTMLElement {
  return screen.getByText(paragraph).parentElement as HTMLElement;
}

const settled = () => screen.findByTestId('guest-content-settled');

/**
 * Stands in for the conversation screen, which reads the same cache entry the
 * route guard filled before activation. What matters is the first value it
 * sees: a send in that window goes out under the wrong source language.
 */
function SessionLanguage({ observed }: Readonly<{ observed: (string | null)[] }>) {
  const { session } = useServices();
  const query = useQuery({
    queryKey: ['session', 'A1B2C3D4'],
    queryFn: () => session.getSession('A1B2C3D4', 'customer'),
  });

  observed.push(query.data?.customerLanguage ?? null);

  return <span data-testid="source-language">{query.data?.customerLanguage ?? 'none'}</span>;
}

const sessionFixture = {
  id: 'A1B2C3D4',
  status: 'active' as const,
  customerLanguage: 'en',
  adminLanguage: 'de',
  createdAt: '2026-08-21T10:00:00+00:00',
  messageCount: 0,
  adminConnected: true,
  customerConnected: true,
};

const route = '/s/A1B2C3D4/info/en';

describe('ConsentScreen', () => {
  it('positions content below the header with the shared content offset', async () => {
    renderWithProviders(tree(), { route });
    await settled();

    expect(
      screen.getByText(/KasselDIALOG is an automatic real-time/).parentElement?.parentElement
        ?.parentElement
    ).toHaveClass('pt-content-top');
  });

  it('shows the chosen language flag', async () => {
    renderWithProviders(tree(), { route });
    await settled();

    expect(screen.getByRole('img', { name: 'English' })).toBeInTheDocument();
  });

  it('continues to the conversation', async () => {
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    expect(await screen.findByText('conversation screen')).toBeInTheDocument();
  });

  // Nothing is stored outside a recording (spec §5.4), so there is nothing to agree
  // to here: recording asks the guest itself, during the conversation.
  it('activates exactly once and asks no storage question', async () => {
    const activate = vi.fn().mockResolvedValue(sessionFixture);

    renderWithProviders(tree(), {
      route,
      services: { session: { getSession: vi.fn(), activate } },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    await waitFor(() => expect(activate).toHaveBeenCalledTimes(1));
    expect(activate).toHaveBeenCalledWith('A1B2C3D4', 'en');
  });

  // The route guard has already cached the session as it was before activation,
  // where the customer's language is still null. Landing on the conversation
  // with that entry sends the first message under the wrong source language,
  // which the gateway rejects with a 400.
  it('publishes the activated session, so the next screen never sees the stale one', async () => {
    const preActivation = {
      id: 'A1B2C3D4',
      status: 'pending' as const,
      customerLanguage: null,
      adminLanguage: 'de',
      createdAt: '2026-08-21T10:00:00+00:00',
      messageCount: 0,
      adminConnected: true,
      customerConnected: false,
    };
    const activated = { ...preActivation, status: 'active' as const, customerLanguage: 'en' };
    const observed: (string | null)[] = [];

    renderWithProviders(tree(<SessionLanguage observed={observed} />), {
      route,
      services: {
        session: {
          // Any read after activation sees the activated session, as the
          // gateway reports it. The stale one is the entry already cached.
          getSession: vi.fn().mockResolvedValue(activated),
          activate: vi.fn().mockResolvedValue(activated),
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Get started' }));
    await screen.findByTestId('source-language');

    expect(observed[0]).toBe('en');
    expect(observed).not.toContain(null);
  });

  describe('Studio content', () => {
    it("shows Studio's explanation for a language Studio provides", async () => {
      server.use(studioEnglish());
      renderWithProviders(tree(), { route });
      await settled();

      expect(screen.getByText('Studio explains the service.')).toBeInTheDocument();
      expect(screen.queryByText(en.consent.howTo)).not.toBeInTheDocument();
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    });

    it('keeps the bundled texts, right to left, for a language Studio does not provide', async () => {
      renderWithProviders(tree(undefined, 'ar'), { route: '/s/A1B2C3D4/info/ar' });
      await settled();

      expect(document.documentElement).toHaveAttribute('dir', 'rtl');
      const block = prose(ar.consent.howTo);
      expect(within(block).getByText(ar.consent.retention)).toBeInTheDocument();
      expect(block.children).toHaveLength(3);
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: ar.consent.getStarted })).toBeInTheDocument();
    });

    it("shows the flag from the guest languages, with Studio's icon", async () => {
      server.use(
        guestLanguagesHandler(
          guestLanguagesBodyWith({
            en: { nativeName: 'English', icon: { url: STUDIO_ICON_URL, alternativeText: 'EN' } },
          })
        )
      );
      renderWithProviders(tree(), { route });
      await settled();

      expect(screen.getByRole('img', { name: 'English' })).toHaveAttribute('src', STUDIO_ICON_URL);
    });

    it('keeps the legal links as the last element of the screen', async () => {
      renderWithProviders(tree(), { route });
      await settled();

      const legal = screen.getByRole('navigation', { name: 'Legal information' });
      expect(legal.parentElement?.lastElementChild).toBe(legal);
      expect(legal.parentElement).toContainElement(
        screen.getByRole('button', { name: 'Get started' })
      );
    });
  });

  it('asks nothing whatever storage fields an earlier gateway still sends', async () => {
    const activate = vi.fn().mockResolvedValue(sessionFixture);
    server.use(
      guestContentHandler((language) =>
        HttpResponse.json({
          ...guestContentBody(language),
          storage: { mode: 'ask' },
          storageQuestionHtml: '<p>Keep the conversation?</p>',
        })
      )
    );
    renderWithProviders(tree(), {
      route,
      services: { session: { getSession: vi.fn(), activate } },
    });
    await settled();

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByText('Keep the conversation?')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Get started' }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('A1B2C3D4', 'en'));
  });

  describe('fallback', () => {
    const failures = {
      'a 404': () => HttpResponse.json({ detail: 'Session not found' }, { status: 404 }),
      'a 503': () => HttpResponse.json({ detail: 'Unavailable' }, { status: 503 }),
      'a network error': () => HttpResponse.error(),
      'a body the mapper rejects': () => HttpResponse.json({ provided: true }),
    };

    it.each(
      Object.entries(failures).flatMap(([name, respond]) =>
        [
          ['en', en.consent.howTo],
          ['ar', ar.consent.howTo],
        ].map(([language, howTo]) => ({ name, respond, language, howTo }))
      )
    )('shows the bundled $language texts after $name', async ({ respond, language, howTo }) => {
      server.use(guestContentHandler(respond));
      renderWithProviders(tree(undefined, language), {
        route: `/s/A1B2C3D4/info/${language}`,
      });
      await settled();

      expect(prose(howTo).children).toHaveLength(3);
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    });

    it('shows a placeholder, not text, while the content is on its way', async () => {
      const { handler, release } = holdGuestContent();
      server.use(handler);
      renderWithProviders(tree(), { route });

      try {
        expect(
          await screen.findByRole('status', { name: 'Loading the information' })
        ).toBeInTheDocument();
        expect(screen.queryByText(en.consent.howTo)).not.toBeInTheDocument();
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Get started' })).not.toBeInTheDocument();
      } finally {
        release();
      }
      await settled();

      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Get started' })).toBeInTheDocument();
    });

    it('keeps the fallback it showed when a reconnect later brings Studio content', async () => {
      server.use(guestContentHandler(() => HttpResponse.json({}, { status: 503 })));
      renderWithProviders(
        <>
          {tree()}
          <CachedStudioContent />
        </>,
        { route }
      );
      await settled();
      expect(prose(en.consent.howTo).children).toHaveLength(3);

      server.use(studioEnglish());
      try {
        onlineManager.setOnline(false);
        onlineManager.setOnline(true);
        await screen.findByTestId('studio-content-cached');
      } finally {
        onlineManager.setOnline(true);
      }

      expect(prose(en.consent.howTo).children).toHaveLength(3);
      expect(screen.queryByText('Studio explains the service.')).not.toBeInTheDocument();
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Get started' })).toBeInTheDocument();
    });

    it('falls back to the bundled texts at the request timeout and keeps them', async () => {
      const { handler, release } = holdGuestContent();
      server.use(handler);
      renderWithProviders(tree(), {
        route,
        services: { config: { ...readConfig({}), requestTimeoutMs: 50 } },
      });

      try {
        expect(await screen.findByRole('button', { name: 'Get started' })).toBeInTheDocument();
        expect(prose(en.consent.howTo).children).toHaveLength(3);
        expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      } finally {
        release();
      }
      await settled();

      // The late answer brings Studio's text; the screen must not swap to it.
      expect(prose(en.consent.howTo).children).toHaveLength(3);
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    });
  });
});
