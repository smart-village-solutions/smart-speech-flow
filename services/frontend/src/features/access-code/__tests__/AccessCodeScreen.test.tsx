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

  it('offers the admin login link', () => {
    renderWithProviders(tree());
    expect(screen.getByRole('link', { name: 'Admin-Login' })).toHaveAttribute('href', '/admin');
  });
});
