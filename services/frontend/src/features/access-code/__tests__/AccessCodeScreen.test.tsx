import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AccessCodeScreen } from '@/features/access-code/AccessCodeScreen';

function tree() {
  return (
    <Routes>
      <Route path="/" element={<AccessCodeScreen />} />
      <Route path="/s/:sessionId/language" element={<p>language screen</p>} />
    </Routes>
  );
}

describe('AccessCodeScreen', () => {
  it('uses the shared fixed header above the start-page content', () => {
    renderWithProviders(tree());

    const header = screen.getByRole('banner');
    expect(header).toHaveClass('bg-white');
    expect(screen.getByRole('img', { name: 'Smart Speech Flow' })).toHaveAttribute(
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

    expect(await screen.findByText('language screen')).toBeInTheDocument();
  });

  it('shows an inline error and keeps the code when the session is unknown', async () => {
    server.use(http.get('*/api/session/ZZZZZZZZ', () => new HttpResponse(null, { status: 404 })));

    renderWithProviders(tree());

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('ZZZZZZZZ');
    await userEvent.click(screen.getByRole('button', { name: 'Weiter' }));

    expect(
      await screen.findByText('Zu diesem Code gibt es keine offene Sitzung.')
    ).toBeInTheDocument();
    expect(screen.getAllByRole('textbox')[0]).toHaveValue('Z');
  });

  it('offers the tenant login chooser link', () => {
    renderWithProviders(tree());
    expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login');
  });

  it('keeps both funding logos side by side in the start-page footer', () => {
    renderWithProviders(tree());

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
});
