import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';

/**
 * The whole path, with nothing faked below the component tree: the real
 * provider, the real sheet, the real repository, the real axios client, and
 * msw standing in for the gateway. The unit tests above each cover one seam;
 * this is the only test that would notice them disagreeing.
 */
const PLACEHOLDER = 'Your ideas, feature requests, or anything that bothered you…';
const route = '/s/A1B2C3D4/language';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/language" element={<LanguageSelectScreen />} />
    </Routes>
  );
}

async function fillTheForm() {
  for (const label of ['Translation quality', 'Performance', 'UI / UX']) {
    const group = screen.getByRole('group', { name: label });
    await userEvent.click(within(group).getByRole('button', { name: '4 stars' }));
  }
  await userEvent.click(screen.getByRole('button', { name: 'Score 8' }));
  await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), 'more languages');
}

const submitButton = () => screen.getByRole('button', { name: /Send feedback|Send again/ });

describe('the feedback flow', () => {
  it('carries the session of the screen it was opened from to the gateway', async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post('*/api/feedback', async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ feedback_id: 'f1' }, { status: 201 });
      })
    );
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
    expect(bodies).toEqual([
      {
        session_id: 'A1B2C3D4',
        translation_quality: 4,
        performance: 4,
        usability: 4,
        net_promoter_score: 8,
        improvements: 'more languages',
        form_version: 'v1',
      },
    ]);
  });

  it('survives an outage and succeeds on the retry without re-entry', async () => {
    let attempts = 0;
    server.use(
      http.post('*/api/feedback', () => {
        attempts += 1;
        return attempts === 1
          ? new HttpResponse(null, { status: 503, headers: { 'Retry-After': '30' } })
          : HttpResponse.json({ feedback_id: 'f2' }, { status: 201 });
      })
    );
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your feedback could not be sent. Your answers have been kept.'
    );
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toHaveValue('more languages');
    expect(screen.queryByText('Thank you!')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Send again/ }));

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it('never thanks anyone for a submission the gateway rejected', async () => {
    server.use(http.post('*/api/feedback', () => new HttpResponse(null, { status: 422 })));
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByText('Thank you!')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('That request could not be processed.');
  });
});
