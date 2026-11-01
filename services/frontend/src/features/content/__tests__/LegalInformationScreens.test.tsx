import { CATALOGUES } from '@/i18n';
import { GuestContentSettled, StaffContentSettled } from '@/test/ContentSettled';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Link, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { onlineManager } from '@tanstack/react-query';
import { useGuestContent } from '@/features/content/useGuestContent';
import { readConfig } from '@/app/config/env';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import { ConsentScreen } from '@/features/consent/ConsentScreen';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import { guestContentBody, staffContentBody } from '@/test/contentFixtures';
import { guestContentHandler, staffContentHandler } from '@/test/handlers';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';

const information = {
  locale: 'de-DE',
  version: 'source-2026-42',
  sections: ['mode2Consent', 'mode3Consent', 'guestRecordingRelease', 'staffRecordingRelease'].map(
    (id) => ({ id, headline: `Source heading ${id}`, bodyHtml: `<p>Source wording ${id}</p>` })
  ),
};

function renderScreen(kind: string) {
  const admin = kind === 'staff conversation';
  const route = kind === 'guest consent' ? '/s/A1B2C3D4/info/ar' : '/s/A1B2C3D4/live';
  server.use(
    http.get('*/api/customer/session/:id', ({ params }) =>
      HttpResponse.json({
        session_id: params.id,
        status: 'active',
        customer_language: 'en',
        admin_language: 'de',
        admin_connected: true,
        customer_connected: true,
        is_active: true,
        can_send_messages: true,
        created_at: '2026-11-01T10:00:00+00:00',
      })
    )
  );
  renderWithProviders(
    <>
      {admin ? (
        <AdminSessionScreen sessionId="A1B2C3D4" onLeave={vi.fn()} onSignOut={vi.fn()} />
      ) : (
        <Routes>
          <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
          <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
        </Routes>
      )}
      {admin ? (
        <StaffContentSettled />
      ) : (
        <GuestContentSettled
          sessionId="A1B2C3D4"
          language={kind === 'guest consent' ? 'ar' : 'en'}
        />
      )}
    </>,
    { route, locale: admin ? 'de' : 'en' }
  );
}

describe.each(['guest consent', 'guest conversation', 'staff conversation'])(
  '%s legal information',
  (kind) => {
    const locale = kind === 'guest consent' ? 'ar' : kind === 'staff conversation' ? 'de' : 'en';
    const title = CATALOGUES[locale].legal.informationTitle;
    it('reads all source sections without any mutation and closes with Escape', async () => {
      server.use(
        guestContentHandler((language) =>
          HttpResponse.json({ ...guestContentBody(language), legalInformation: information })
        ),
        staffContentHandler({ ...staffContentBody, legalInformation: information })
      );
      const mutations: string[] = [];
      const observe = ({ request }: { request: Request }) => {
        if (request.method !== 'GET') mutations.push(`${request.method} ${request.url}`);
      };
      server.events.on('request:start', observe);
      try {
        const user = userEvent.setup();
        renderScreen(kind);
        const trigger = await screen.findByRole('button', {
          name: title,
        });
        await user.click(trigger);
        const dialog = screen.getByRole('dialog');
        for (const section of information.sections) {
          expect(
            within(dialog).getByRole('heading', { name: section.headline })
          ).toBeInTheDocument();
          expect(within(dialog).getByText(`Source wording ${section.id}`)).toBeInTheDocument();
        }
        expect(within(dialog).getByText(/de-DE/)).toHaveTextContent('source-2026-42');
        expect(within(dialog).getAllByRole('button')).toHaveLength(1);
        expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument();
        await user.keyboard('{Escape}');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
        expect(mutations).toEqual([]);
      } finally {
        server.events.removeListener('request:start', observe);
      }
    });

    it.each([undefined, null, { ...information, sections: [] }])(
      'hides an absent or invalid block %j',
      async (legalInformation) => {
        server.use(
          guestContentHandler((language) =>
            HttpResponse.json({ ...guestContentBody(language), legalInformation })
          ),
          staffContentHandler({ ...staffContentBody, legalInformation })
        );
        renderScreen(kind);
        await screen.findByTestId(
          kind === 'staff conversation' ? 'staff-content-settled' : 'guest-content-settled'
        );
        expect(
          screen.queryByRole('button', {
            name: title,
          })
        ).not.toBeInTheDocument();
      }
    );
  }
);

// The entry introduces the service; counsel wording is available only on request.
describe('ordinary conversation entry', () => {
  it.each([undefined, information])(
    'keeps all counsel wording out of the entry with compatibility information %j',
    async (documentationInformation) => {
      server.use(
        guestContentHandler((language) =>
          HttpResponse.json({
            ...guestContentBody(language),
            storage: { mode: 'disabled' },
            storageQuestionHtml: null,
            legalInformation: information,
            documentationInformation,
          })
        )
      );
      renderScreen('guest consent');
      const trigger = await screen.findByRole('button', {
        name: CATALOGUES.ar.legal.informationTitle,
      });
      expect(
        screen.getByText(
          CATALOGUES.ar.consent.intro.replace('$t(app.name)', CATALOGUES.ar.app.name)
        )
      ).toBeInTheDocument();
      expect(screen.getByText(CATALOGUES.ar.consent.howTo)).toBeInTheDocument();
      expect(
        screen.getByText(
          CATALOGUES.ar.consent.intro.replace('$t(app.name)', CATALOGUES.ar.app.name)
        ).parentElement?.children
      ).toHaveLength(2);
      expect(screen.queryByRole('region')).not.toBeInTheDocument();
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      for (const section of information.sections) {
        expect(screen.queryByRole('heading', { name: section.headline })).not.toBeInTheDocument();
        expect(screen.queryByText(`Source wording ${section.id}`)).not.toBeInTheDocument();
      }
      await userEvent.click(trigger);
      const dialog = screen.getByRole('dialog');
      for (const section of information.sections) {
        expect(within(dialog).getByRole('heading', { name: section.headline })).toBeInTheDocument();
        expect(within(dialog).getByText(`Source wording ${section.id}`)).toBeInTheDocument();
      }
      expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument();
    }
  );
});

describe('entry legal snapshot', () => {
  it.each(['pending', 'failed'])(
    'shows route language terms when the language list is %s',
    async (state) => {
      let release!: () => void;
      const pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      server.use(
        http.get('*/api/customer/session/:id/languages', async () => {
          if (state === 'pending') await pending;
          return HttpResponse.json({}, { status: 503 });
        }),
        guestContentHandler((language) =>
          HttpResponse.json({ ...guestContentBody(language), legalInformation: information })
        )
      );
      try {
        renderScreen('guest consent');
        await userEvent.click(
          await screen.findByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
        );
        expect(
          within(screen.getByRole('dialog')).getByText('Source wording mode2Consent')
        ).toBeInTheDocument();
      } finally {
        release();
      }
    }
  );

  function CachedInformation() {
    const { content } = useGuestContent('A1B2C3D4', 'en');
    return content?.legalInformation ? <span data-testid="information-cached" /> : null;
  }

  it.each(['timeout', 'reconnect'])(
    'keeps the reference absent after a %s fallback',
    async (reason) => {
      let release!: () => void;
      const pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      server.use(
        guestContentHandler(async (language) => {
          if (reason === 'reconnect') return HttpResponse.json({}, { status: 503 });
          await pending;
          return HttpResponse.json({
            ...guestContentBody(language),
            legalInformation: information,
          });
        })
      );
      renderWithProviders(
        <>
          <Routes>
            <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
          </Routes>
          <CachedInformation />
        </>,
        {
          route: '/s/A1B2C3D4/info/en',
          services: { config: { ...readConfig({}), requestTimeoutMs: 40 } },
        }
      );
      try {
        await screen.findByRole('button', { name: CATALOGUES.en.consent.getStarted });
        if (reason === 'reconnect') {
          server.use(
            guestContentHandler((language) =>
              HttpResponse.json({ ...guestContentBody(language), legalInformation: information })
            )
          );
          onlineManager.setOnline(false);
          onlineManager.setOnline(true);
        } else release();
        await screen.findByTestId('information-cached');
        expect(screen.queryByText('Source wording mode2Consent')).not.toBeInTheDocument();
        expect(
          screen.queryByRole('button', { name: CATALOGUES.en.legal.informationTitle })
        ).not.toBeInTheDocument();
      } finally {
        release();
        onlineManager.setOnline(true);
      }
    }
  );

  it('takes a fresh snapshot when the route language changes', async () => {
    server.use(
      guestContentHandler((language) =>
        HttpResponse.json({
          ...guestContentBody(language),
          legalInformation: {
            ...information,
            sections: information.sections.map((section) => ({
              ...section,
              bodyHtml: `<p>${language} wording ${section.id}</p>`,
            })),
          },
        })
      )
    );
    renderWithProviders(
      <>
        <Link to="/s/A1B2C3D4/info/ar">Switch language</Link>
        <Routes>
          <Route path="/s/:sessionId/info/:languageCode" element={<ConsentScreen />} />
        </Routes>
      </>,
      { route: '/s/A1B2C3D4/info/en' }
    );
    await userEvent.click(
      await screen.findByRole('button', { name: CATALOGUES.en.legal.informationTitle })
    );
    expect(
      within(screen.getByRole('dialog')).getByText('en wording mode2Consent')
    ).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('link', { name: 'Switch language' }));
    await userEvent.click(
      await screen.findByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
    );
    expect(
      within(screen.getByRole('dialog')).getByText('ar wording mode2Consent')
    ).toBeInTheDocument();
    expect(screen.queryByText('en wording mode2Consent')).not.toBeInTheDocument();
  });
});

it.each([
  ['AR-eg', 'rtl'],
  ['fa-IR', 'rtl'],
  ['de-DE', 'ltr'],
])('sets the reference wording direction from source locale %s', async (locale, direction) => {
  server.use(
    guestContentHandler((language) =>
      HttpResponse.json({
        ...guestContentBody(language),
        legalInformation: { ...information, locale },
      })
    )
  );
  renderScreen('guest consent');
  await userEvent.click(
    await screen.findByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
  );
  const wording = within(screen.getByRole('dialog'))
    .getByText('Source wording mode2Consent')
    .closest('[lang]');
  expect(wording).toHaveAttribute('lang', locale);
  expect(wording).toHaveAttribute('dir', direction);
});
