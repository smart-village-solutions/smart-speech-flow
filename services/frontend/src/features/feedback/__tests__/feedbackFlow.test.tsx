import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { server } from '@/test/setup';
import { KASSEL_REVISION, guestContentBody } from '@/test/contentFixtures';
import { feedbackFormChanged, feedbackHandler, guestContentHandler } from '@/test/handlers';
import { recordRequests } from '@/test/recordRequests';
import { renderWithProviders } from '@/test/renderWithProviders';
import { LanguageSelectScreen } from '@/features/language-select/LanguageSelectScreen';

/**
 * The whole path, with nothing faked below the component tree: the real
 * provider, the real sheet, the real repository, the real axios client, and
 * msw standing in for the gateway. The unit tests above each cover one seam;
 * this is the only test that would notice them disagreeing.
 */
// Kassel provides English, so the language screen (pinned to en) shows Studio's guest form.
const PLACEHOLDER = 'Your ideas or complaints';
const BUNDLED_PLACEHOLDER = 'Your ideas, feature requests, or anything that bothered you…';
const route = '/s/A1B2C3D4/language';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/language" element={<LanguageSelectScreen />} />
    </Routes>
  );
}

async function fillTheForm() {
  await screen.findByPlaceholderText(PLACEHOLDER);
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
      feedbackHandler('public', (body) => {
        bodies.push(body);
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
        audience: 'guest',
        session_id: 'A1B2C3D4',
        locale: 'en',
        form_source: 'studio',
        configuration_revision: KASSEL_REVISION,
        answers: {
          translationQuality: 4,
          performance: 4,
          usability: 4,
          recommendation: 8,
          improvementIdeas: 'more languages',
        },
      },
    ]);
  });

  it('survives an outage and succeeds on the retry without re-entry', async () => {
    let attempts = 0;
    server.use(
      feedbackHandler('public', () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json(
              { detail: { error_code: 'feedback_form_unavailable', message: 'Retry later' } },
              { status: 503, headers: { 'Retry-After': '30' } }
            )
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
    server.use(
      feedbackHandler('public', () =>
        HttpResponse.json(
          { detail: { error_code: 'feedback_request_invalid', message: 'Invalid' } },
          { status: 422 }
        )
      )
    );
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.queryByText('Thank you!')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('That request could not be processed.');
    // A client bug: the same body would be refused again.
    expect(submitButton()).toBeDisabled();
  });
});

/** Kassel's English content, republished without `usability` and with an optional 1-5 recommendation. */
function republishedEnglish() {
  const english = guestContentBody('en');
  if (!('feedback' in english)) throw new Error('English is provided');
  return {
    ...english,
    revision: 'sha256:republished',
    feedback: {
      ...english.feedback,
      questions: english.feedback.questions
        .filter((question) => question.id !== 'usability')
        .map((question) =>
          question.id === 'recommendation'
            ? { ...question, required: false, min: 1, max: 5 }
            : question
        ),
    },
  };
}

describe('a form that changed while it was open', () => {
  it('offers a reload that keeps the answers the new form still accepts', async () => {
    let republished = false;
    const bodies: Record<string, unknown>[] = [];
    const contentReads = recordRequests((request) => request.url.includes('/content/en'));
    const cacheControls: (string | null)[] = [];
    server.use(
      http.get('*/api/customer/session/:id/content/:language', ({ request, params }) => {
        cacheControls.push(request.headers.get('Cache-Control'));
        const language = String(params.language);
        return HttpResponse.json(republished ? republishedEnglish() : guestContentBody(language));
      }),
      feedbackHandler('public', (body) => {
        if (!republished) {
          republished = true;
          return feedbackFormChanged();
        }
        bodies.push(body);
        return HttpResponse.json({ feedback_id: 'f3' }, { status: 201 });
      })
    );
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The form has changed in the meantime.');
    expect(submitButton()).toBeDisabled();
    const readsBefore = contentReads.length;

    await userEvent.click(within(alert).getByRole('button', { name: 'Load the new form' }));

    await waitFor(() =>
      expect(screen.queryByRole('group', { name: 'UI / UX' })).not.toBeInTheDocument()
    );
    expect(await screen.findByRole('group', { name: 'Translation quality' })).toBeInTheDocument();
    expect(contentReads.length).toBeGreaterThan(readsBefore);
    // The reload must not be answered from the browser's copy of the old form.
    expect(cacheControls.slice(readsBefore)).toEqual(['no-cache']);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    const quality = screen.getByRole('group', { name: 'Translation quality' });
    expect(within(quality).getByRole('button', { name: '4 stars' })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toHaveValue('more languages');
    // 8 lies outside the new 1-5 range: the form cannot show it, so it is dropped
    // rather than left to block the button invisibly.
    for (const score of [1, 2, 3, 4, 5]) {
      expect(screen.getByRole('button', { name: `Score ${score}` })).toHaveAttribute(
        'aria-pressed',
        'false'
      );
    }
    expect(submitButton()).toBeEnabled();

    await userEvent.click(submitButton());

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
    expect(bodies).toEqual([
      expect.objectContaining({
        configuration_revision: 'sha256:republished',
        answers: { translationQuality: 4, performance: 4, improvementIdeas: 'more languages' },
      }),
    ]);
  });

  it('falls back to the bundled form when the reload cannot read the new one', async () => {
    let changed = false;
    const bodies: Record<string, unknown>[] = [];
    server.use(
      guestContentHandler((language) =>
        changed
          ? new HttpResponse(null, { status: 503 })
          : HttpResponse.json(guestContentBody(language))
      ),
      feedbackHandler('public', (body) => {
        if (!changed) {
          changed = true;
          return feedbackFormChanged();
        }
        bodies.push(body);
        return HttpResponse.json({ feedback_id: 'f4' }, { status: 201 });
      })
    );
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());
    const alert = await screen.findByRole('alert');
    await userEvent.click(within(alert).getByRole('button', { name: 'Load the new form' }));

    // The cached Studio form is the one the gateway refused; the bundled form is the way out.
    expect(await screen.findByPlaceholderText(BUNDLED_PLACEHOLDER)).toHaveValue('more languages');
    await userEvent.click(submitButton());

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
    expect(bodies).toEqual([
      expect.objectContaining({ form_source: 'bundled', configuration_revision: null }),
    ]);
  });

  it('keeps offering the reload while the stale form is edited', async () => {
    server.use(feedbackHandler('public', () => feedbackFormChanged()));
    renderWithProviders(tree(), { route });

    await userEvent.click(await screen.findByRole('button', { name: 'Feedback' }));
    await fillTheForm();
    await userEvent.click(submitButton());
    await screen.findByRole('alert');

    const performance = screen.getByRole('group', { name: 'Performance' });
    await userEvent.click(within(performance).getByRole('button', { name: '2 stars' }));

    // The gateway refused the form, not an answer: an edit cannot make it fit.
    expect(
      within(screen.getByRole('alert')).getByRole('button', { name: 'Load the new form' })
    ).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });
});
