import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import type { Session } from '@/domain/session/session.types';
import { SESSION_ID } from '@/test/handlers';

function sessionIn(customerLanguage: string | null, status: Session['status'] = 'active'): Session {
  return {
    id: SESSION_ID,
    status,
    customerLanguage,
    adminLanguage: 'de',
    createdAt: '2026-08-21T10:00:00+00:00',
    messageCount: 0,
    adminConnected: true,
    customerConnected: true,
  };
}

function sessionService(session: Session) {
  return {
    getSession: vi.fn().mockResolvedValue(session),
    activate: vi.fn().mockResolvedValue(session),
    reportActivity: vi.fn().mockResolvedValue(undefined),
  };
}

beforeEach(() => {
  document.documentElement.dir = '';
  document.documentElement.lang = '';
});

describe('the language the customer sees', () => {
  it('is German before a language has been chosen', async () => {
    renderWithProviders(<AppRoutes />, { route: '/' });

    expect(await screen.findByText('Code eingeben')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('de');
  });

  it('is English on the language picker, which no customer language covers yet', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/language`,
      services: { session: sessionService(sessionIn(null, 'pending')) },
    });

    expect(await screen.findByText('Choose your language')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
  });

  it('follows the choice from the information screen onwards', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/language`,
      services: { session: sessionService(sessionIn('tr', 'pending')) },
    });

    await userEvent.click(await screen.findByText('Türkçe'));

    expect(await screen.findByRole('button', { name: 'Başlayın' })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('tr');
  });

  it('follows the session language on the conversation screen, which carries no code in its url', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/live`,
      services: { session: sessionService(sessionIn('uk')) },
    });

    expect(await screen.findByLabelText('Записати')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('uk');
  });

  it('returns to German when the customer goes back to the start', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/info/fa`,
      services: { session: sessionService(sessionIn('fa', 'pending')) },
    });

    await userEvent.click(await screen.findByLabelText('خانه'));

    expect(await screen.findByText('Code eingeben')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('de');
  });
});

describe('right-to-left languages', () => {
  it('turns the document right to left for Arabic', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/info/ar`,
      services: { session: sessionService(sessionIn('ar', 'pending')) },
    });

    expect(await screen.findByRole('button', { name: 'لنبدأ' })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('turns the conversation right to left for Persian', async () => {
    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/live`,
      services: { session: sessionService(sessionIn('fa')) },
    });

    expect(await screen.findByLabelText('ضبط')).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('rtl');
  });

  // Kurmancî is Latin script, unlike Sorani; Ge'ez also runs left to right.
  it('leaves Kurmancî and Tigrinya left to right', async () => {
    const { unmount } = renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/info/ku`,
      services: { session: sessionService(sessionIn('ku', 'pending')) },
    });
    expect(await screen.findByRole('button', { name: 'Dest pê bike' })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('ltr');
    unmount();

    renderWithProviders(<AppRoutes />, {
      route: `/s/${SESSION_ID}/info/ti`,
      services: { session: sessionService(sessionIn('ti', 'pending')) },
    });
    expect(await screen.findByRole('button', { name: 'ንጀምር' })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('ltr');
  });
});
