import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes, useLocation, useParams } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { installationBody } from '@/test/contentFixtures';
import { ContentSettled } from '@/test/ContentSettled';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';
import { RequireSession } from '@/app/router/RequireSession';

function LocationState() {
  return <output data-testid="location-state">{JSON.stringify(useLocation().state)}</output>;
}

function LanguageScreen() {
  return <p>language screen {useParams().sessionId}</p>;
}

function tree() {
  return (
    <Routes>
      <Route path="/" element={<AccessCodeScreen />} />
      <Route path="/s/:sessionId/language" element={<LanguageScreen />} />
    </Routes>
  );
}

function serveInstallation(overrides: Partial<typeof installationBody>) {
  server.use(
    http.get('*/api/content/installation', () =>
      HttpResponse.json({ ...installationBody, ...overrides })
    )
  );
}

/** Renders the start page and waits until its installation content has arrived or failed. */
async function renderSettled(options?: Parameters<typeof renderWithProviders>[1]) {
  renderWithProviders(
    <>
      {tree()}
      <ContentSettled />
    </>,
    { publicContent: 'fetched', ...options }
  );
  await screen.findByTestId('public-content-settled');
}

describe('AccessCodeScreen', () => {
  it('uses the shared fixed header above the start-page content', async () => {
    await renderSettled({ brand: 'kassel' });

    const header = screen.getByRole('banner');
    expect(header).toHaveClass('bg-white');
    expect(screen.getByRole('img', { name: 'KasselDIALOG' })).toHaveAttribute(
      'src',
      '/assets/Logo.png'
    );
    expect(screen.getByRole('heading', { name: 'Code eingeben' }).parentElement).toHaveClass(
      'pt-content-top'
    );
    expect(screen.queryByRole('button', { name: 'Zurück' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument();
  });

  it('keeps continue disabled until every character is entered', async () => {
    renderWithProviders(tree());

    const submit = screen.getByRole('button', { name: 'Weiter' });
    expect(submit).toBeDisabled();

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('A1B2C3D4');

    expect(submit).toBeEnabled();
  });

  it('navigates to the language picker for a valid code', async () => {
    renderWithProviders(tree());

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('A1B2C3D4');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));

    expect(await screen.findByText('language screen A1B2C3D4')).toBeInTheDocument();
  });

  it('shows an inline error and keeps the code when the session is unknown', async () => {
    server.use(
      http.get('*/api/customer/session/ZZZZZZZZ', () => new HttpResponse(null, { status: 404 }))
    );

    renderWithProviders(tree());

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('ZZZZZZZZ');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));

    expect(
      await screen.findByText('Zu diesem Code gibt es keine offene Sitzung.')
    ).toBeInTheDocument();
    expect(screen.getAllByRole('textbox')[0]).toHaveValue('Z');
  });

  it('says the conversation already has a guest when the code is taken', async () => {
    server.use(
      http.get('*/api/customer/session/A1B2C3D4', () =>
        HttpResponse.json({ detail: { error_code: 'SESSION_HAS_GUEST' } }, { status: 409 })
      )
    );

    renderWithProviders(tree());

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('A1B2C3D4');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));

    // The screen settles on German after its first paint, so wait for that text.
    expect(await screen.findByText('Diese Unterhaltung hat bereits einen Gast.')).toHaveAttribute(
      'role',
      'alert'
    );
  });

  it('shows the same message when a join link of a taken conversation is opened', async () => {
    server.use(
      http.get('*/api/customer/session/A1B2C3D4', () =>
        HttpResponse.json({ detail: { error_code: 'SESSION_HAS_GUEST' } }, { status: 409 })
      )
    );

    renderWithProviders(
      <>
        <Routes>
          <Route path="/" element={<AccessCodeScreen />} />
          <Route path="/s/:sessionId" element={<RequireSession />}>
            <Route path="language" element={<LanguageScreen />} />
          </Route>
        </Routes>
        <LocationState />
      </>,
      { route: '/s/A1B2C3D4/language' }
    );

    // The screen settles on German after its first paint, so wait for that text.
    expect(await screen.findByText('Diese Unterhaltung hat bereits einen Gast.')).toHaveAttribute(
      'role',
      'alert'
    );
    expect(screen.queryByText(/language screen/)).not.toBeInTheDocument();
    // Read once and dropped, so a reload or Back does not bring the notice back.
    await waitFor(() => expect(screen.getByTestId('location-state')).toHaveTextContent('null'));
  });

  it('offers the tenant login chooser link', async () => {
    await renderSettled();
    expect(screen.getByRole('link', { name: 'Login für Nutzer' })).toHaveAttribute(
      'href',
      '/login'
    );
  });

  it('keeps both funding logos side by side in the start-page footer', async () => {
    await renderSettled();

    const funding = screen.getByRole('img', { name: 'Fördermittelgeber' });
    const city = screen.getByRole('img', { name: 'Stadt Kassel' });

    expect(funding).toHaveAttribute('src', '/assets/Foerdermittelgeber.png');
    expect(city).toHaveAttribute('src', '/assets/Stadt.png');
    expect(funding.parentElement).toBe(city.parentElement);
    expect(funding.parentElement).toHaveClass('grid-cols-2');
    expect(funding.parentElement).toHaveClass('max-w-app');

    const footer = funding.closest('footer');
    expect(footer).toHaveClass('w-screen', 'bg-white', 'shadow-[0_-2px_6px_rgba(0,0,0,0.08)]');
    expect(document.querySelector('[data-screen-shell]')).toHaveClass('overflow-x-clip');
  });

  describe('installation texts', () => {
    it('shows Studio texts on the German start page', async () => {
      serveInstallation({
        startpage: { enterCode: 'Gesprächscode eingeben', send: 'Los', login: 'Login für Nutzer' },
      });

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Gesprächscode eingeben' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Los' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Login für Nutzer' })).toHaveAttribute(
        'href',
        '/login'
      );
    });

    it('keeps bundled texts while installation content is unavailable (503)', async () => {
      server.use(
        http.get('*/api/content/installation', () =>
          HttpResponse.json(
            { detail: 'Studio content is temporarily unavailable' },
            { status: 503 }
          )
        )
      );

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Weiter' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login');
    });

    it('keeps bundled texts when the content is in another language', async () => {
      serveInstallation({
        locale: 'en-GB',
        startpage: { enterCode: 'Enter code', send: 'Next', login: 'Staff login' },
      });

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
      expect(screen.queryByText('Enter code')).not.toBeInTheDocument();
      expect(screen.queryByText('Staff login')).not.toBeInTheDocument();
    });
  });
});
