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

// The ordinary conversation entry must expose documentation wording without
// treating the page visit or Get Started as a recording release.
describe('ordinary conversation entry', () => {
  it('shows documentation and guest release wording inline, retaining the separate reference dialog', async () => {
    server.use(
      guestContentHandler((language) =>
        HttpResponse.json({
          ...guestContentBody(language),
          storage: { mode: 'disabled' },
          storageQuestionHtml: null,
          legalInformation: information,
        })
      )
    );
    renderScreen('guest consent');
    const region = await screen.findByRole('region', {
      name: CATALOGUES.ar.legal.informationTitle,
    });
    expect(region).not.toHaveAttribute('lang');
    expect(region).not.toHaveAttribute('dir');
    const wording = within(region).getByText('Source wording mode2Consent').closest('[lang]');
    expect(wording).toHaveAttribute('lang', 'de-DE');
    expect(wording).toHaveAttribute('dir', 'auto');
    expect(wording).not.toContainElement(
      within(region).getByText(CATALOGUES.ar.legal.informationNotice)
    );
    for (const id of ['mode2Consent', 'guestRecordingRelease']) {
      expect(within(region).getByText(`Source wording ${id}`)).toBeInTheDocument();
    }
    for (const id of ['mode3Consent', 'staffRecordingRelease']) {
      expect(within(region).queryByText(`Source wording ${id}`)).not.toBeInTheDocument();
    }
    expect(within(region).getByText(/de-DE/)).toHaveTextContent('source-2026-42');
    expect(within(region).queryByRole('button')).not.toBeInTheDocument();
    expect(within(region).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
    ).toBeInTheDocument();
  });
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
        expect(await screen.findByText('Source wording mode2Consent')).toBeInTheDocument();
      } finally {
        release();
      }
    }
  );

  it.each([null, { ...information, sections: information.sections.slice(0, 1) }])(
    'does not use reference wording when documentation information is %j',
    async (documentationInformation) => {
      server.use(
        guestContentHandler((language) =>
          HttpResponse.json({
            ...guestContentBody(language),
            legalInformation: information,
            documentationInformation,
          })
        )
      );
      renderScreen('guest consent');
      await screen.findByTestId('guest-content-settled');
      expect(
        screen.queryByRole('region', { name: CATALOGUES.ar.legal.informationTitle })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
      ).toBeInTheDocument();
    }
  );

  it('uses a complete independent documentation pair while retaining the full reference', async () => {
    const pair = {
      ...information,
      version: 'pair-version',
      sections: information.sections
        .filter(({ id }) => ['mode2Consent', 'guestRecordingRelease'].includes(id))
        .map((section) => ({ ...section, bodyHtml: `<p>Pair wording ${section.id}</p>` })),
    };
    server.use(
      guestContentHandler((language) =>
        HttpResponse.json({
          ...guestContentBody(language),
          legalInformation: information,
          documentationInformation: pair,
        })
      )
    );
    renderScreen('guest consent');
    expect(await screen.findByText('Pair wording mode2Consent')).toBeInTheDocument();
    expect(screen.queryByText('Source wording mode2Consent')).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: CATALOGUES.ar.legal.informationTitle })
    );
    expect(
      within(screen.getByRole('dialog')).getByText('Source wording mode3Consent')
    ).toBeInTheDocument();
  });

  it('requires a complete pair from a legacy reference response', async () => {
    server.use(
      guestContentHandler((language) =>
        HttpResponse.json({
          ...guestContentBody(language),
          legalInformation: { ...information, sections: information.sections.slice(0, 1) },
        })
      )
    );
    renderScreen('guest consent');
    await screen.findByTestId('guest-content-settled');
    expect(
      screen.queryByRole('region', { name: CATALOGUES.ar.legal.informationTitle })
    ).not.toBeInTheDocument();
  });

  function CachedInformation() {
    const { content } = useGuestContent('A1B2C3D4', 'en');
    return content?.legalInformation ? <span data-testid="information-cached" /> : null;
  }

  it.each(['timeout', 'reconnect'])(
    'keeps both inline and reference absent after a %s fallback',
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
    expect(await screen.findByText('en wording mode2Consent')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'Switch language' }));
    expect(await screen.findByText('ar wording mode2Consent')).toBeInTheDocument();
    expect(screen.queryByText('en wording mode2Consent')).not.toBeInTheDocument();
  });
});
