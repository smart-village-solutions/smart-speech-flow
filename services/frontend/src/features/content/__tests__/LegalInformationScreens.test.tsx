import { GuestContentSettled, StaffContentSettled } from '@/test/ContentSettled';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
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
          name: /Consent and recording terms|Einwilligung und Aufnahmebedingungen/,
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
            name: /Consent and recording terms|Einwilligung und Aufnahmebedingungen/,
          })
        ).not.toBeInTheDocument();
      }
    );
  }
);
