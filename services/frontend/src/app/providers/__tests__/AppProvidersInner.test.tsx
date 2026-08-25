import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { AppProvidersInner } from '@/app/providers/AppProvidersInner';
import { useLocale } from '@/app/providers/locale';
import { useServices, type Services } from '@/app/providers/services';
import { readConfig } from '@/app/config/env';

const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });

function setup() {
  const rendered: Services[] = [];

  function Probe() {
    const services = useServices();
    const { locale, setLocale } = useLocale();
    rendered.push(services);

    return (
      <div>
        <span data-testid="locale">{locale}</span>
        <button type="button" onClick={() => setLocale('ar')}>
          switch
        </button>
        <button type="button" onClick={() => void services.session.getSession('A1B2C3D4')}>
          fetch
        </button>
      </div>
    );
  }

  render(
    <AppProvidersInner config={config}>
      <Probe />
    </AppProvidersInner>
  );

  return rendered;
}

const click = (name: string) => userEvent.click(screen.getByRole('button', { name }));

describe('AppProvidersInner', () => {
  // The services own the socket factory and the repositories. Rebuilding them
  // tore down the live conversation socket and refetched history the moment the
  // session's language arrived, which is on every load of the conversation.
  it('keeps one service graph across a locale change', async () => {
    const rendered = setup();
    const first = rendered[0];

    await click('switch');

    expect(screen.getByTestId('locale').textContent).toBe('ar');
    expect(rendered.at(-1)).toBe(first);
  });

  it('still sends the locale in force at the time of the request', async () => {
    const locales: string[] = [];
    server.use(
      http.get('http://api.test/api/session/A1B2C3D4', ({ request }) => {
        locales.push(request.headers.get('Accept-Language') ?? '');
        return HttpResponse.json({
          id: 'A1B2C3D4',
          status: 'active',
          customer_language: 'ar',
          admin_language: 'de',
          created_at: '2026-08-21T10:00:00+00:00',
          message_count: 0,
          admin_connected: true,
          customer_connected: true,
        });
      })
    );

    setup();

    await click('fetch');
    await waitFor(() => expect(locales).toHaveLength(1));

    await click('switch');
    await click('fetch');
    await waitFor(() => expect(locales).toHaveLength(2));

    expect(locales).toEqual(['de', 'ar']);
  });
});
