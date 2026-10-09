import { HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useFeedback } from '@/app/providers/feedback';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { INSTALLATION_REVISION, KASSEL_REVISION } from '@/test/contentFixtures';
import { feedbackHandler } from '@/test/handlers';
import { server } from '@/test/setup';

/**
 * The provider sits above <Routes>, so useParams cannot reach a session here.
 * Whatever the caller knows has to travel with the call that opens the sheet.
 */
function Opener({ sessions }: Readonly<{ sessions: (string | null)[] }>) {
  const { openFeedback } = useFeedback();

  return (
    <>
      {sessions.map((session) => (
        <button
          key={String(session)}
          type="button"
          onClick={() =>
            openFeedback(
              session === null
                ? { kind: 'staff', sessionId: null }
                : { kind: 'guest', sessionId: session }
            )
          }
        >
          {`open ${String(session)}`}
        </button>
      ))}
    </>
  );
}

function render(sessions: (string | null)[]) {
  const recorded = vi.fn();
  renderWithProviders(<Opener sessions={sessions} />, {
    services: { feedback: createStubFeedbackSink(recorded) },
  });
  return recorded;
}

const submitButton = () => screen.getByRole('button', { name: /Send feedback/ });

/** Outlasts the sheet's 300ms exit transition (export 146). */
function settled() {
  return new Promise((resolve) => {
    setTimeout(resolve, 350);
  });
}

async function submitTheForm() {
  // Guest and staff sheets wait for their content before showing a form.
  await screen.findByRole('group', { name: 'Translation quality' });
  for (const label of ['Translation quality', 'Performance', 'UI / UX']) {
    const group = screen.getByRole('group', { name: label });
    await userEvent.click(within(group).getByRole('button', { name: '5 stars' }));
  }
  await userEvent.click(screen.getByRole('button', { name: 'Score 9' }));
  await userEvent.click(submitButton());
}

describe('FeedbackProvider', () => {
  it('submits under the session the caller opened it with', async () => {
    const recorded = render(['A1B2C3D4']);

    await userEvent.click(screen.getByRole('button', { name: 'open A1B2C3D4' }));
    await submitTheForm();

    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith(expect.objectContaining({ sessionId: 'A1B2C3D4' }))
    );
  });

  it('submits without a session where the caller has none', async () => {
    // The admin dashboard offers feedback outside any session; the gateway
    // stores MISSING_REFERENCE rather than rejecting it (spec O1).
    const recorded = render([null]);

    await userEvent.click(screen.getByRole('button', { name: 'open null' }));
    await submitTheForm();

    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith(expect.objectContaining({ sessionId: null }))
    );
  });

  it('reopens under the newer session rather than the first one seen', async () => {
    const recorded = render(['A1B2C3D4', 'E5F6G7H8']);

    await userEvent.click(screen.getByRole('button', { name: 'open A1B2C3D4' }));
    await userEvent.keyboard('{Escape}');
    await settled();
    await userEvent.click(screen.getByRole('button', { name: 'open E5F6G7H8' }));
    await submitTheForm();

    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith(expect.objectContaining({ sessionId: 'E5F6G7H8' }))
    );
  });
});

function OriginOpener({ origin }: Readonly<{ origin: FeedbackOrigin }>) {
  const { openFeedback } = useFeedback();

  return (
    <button type="button" onClick={() => openFeedback(origin)}>
      open
    </button>
  );
}

describe('openFeedback contexts', () => {
  it.each([
    ['public', { kind: 'public' } as const, null, 'installation'],
    ['guest', { kind: 'guest', sessionId: 'A1B2C3D4' } as const, 'A1B2C3D4', 'guest'],
    ['staff in a session', { kind: 'staff', sessionId: 'E5F6G7H8' } as const, 'E5F6G7H8', 'staff'],
    ['staff on the dashboard', { kind: 'staff', sessionId: null } as const, null, 'staff'],
  ])(
    'carries a %s context through to the submission',
    async (_name, origin, sessionId, audience) => {
      const recorded = vi.fn();
      renderWithProviders(<OriginOpener origin={origin} />, {
        services: { feedback: createStubFeedbackSink(recorded) },
      });

      await userEvent.click(screen.getByRole('button', { name: 'open' }));
      await submitTheForm();

      await waitFor(() =>
        expect(recorded).toHaveBeenCalledWith(expect.objectContaining({ sessionId, audience }))
      );
    }
  );
});

interface Labels {
  ratings: string[];
  star: string;
  score: string;
  submit: RegExp;
}

const ENGLISH: Labels = {
  ratings: ['Translation quality', 'Performance', 'UI / UX'],
  star: '5 stars',
  score: 'Score 9',
  submit: /Send feedback/,
};
const GERMAN: Labels = {
  ratings: ['Übersetzungsqualität', 'Geschwindigkeit', 'Bedienung'],
  star: '5 Sterne',
  score: 'Wert 9',
  submit: /Feedback senden/,
};
const ARABIC: Labels = {
  ratings: ['جودة الترجمة', 'الأداء', 'الواجهة وسهولة الاستخدام'],
  star: '5 نجوم',
  score: 'التقييم 9',
  submit: /إرسال الملاحظات/,
};

/** Opens the sheet from `origin`, answers every required question, and returns what reached the gateway. */
async function sendThrough(origin: FeedbackOrigin, locale: string, labels: Labels) {
  const sent: { path: string; body: Record<string, unknown> }[] = [];
  const capture = (path: string) => (body: Record<string, unknown>) => {
    sent.push({ path, body });
    return HttpResponse.json({ feedback_id: 'f1' }, { status: 201 });
  };
  server.use(
    feedbackHandler('public', capture('/api/feedback')),
    feedbackHandler('admin', capture('/api/admin/feedback'))
  );
  renderWithProviders(<OriginOpener origin={origin} />, { locale });

  await userEvent.click(screen.getByRole('button', { name: 'open' }));
  for (const label of labels.ratings) {
    const group = await screen.findByRole('group', { name: label });
    await userEvent.click(within(group).getByRole('button', { name: labels.star }));
  }
  await userEvent.click(screen.getByRole('button', { name: labels.score }));
  await userEvent.click(screen.getByRole('button', { name: labels.submit }));
  await waitFor(() => expect(sent).toHaveLength(1));
  return sent[0];
}

const ANSWERS = { translationQuality: 5, performance: 5, usability: 5, recommendation: 9 };

describe('what each audience sends', () => {
  it("sends installation feedback on the start page's Studio form, without a session", async () => {
    expect(await sendThrough({ kind: 'public' }, 'de', GERMAN)).toEqual({
      path: '/api/feedback',
      body: {
        audience: 'installation',
        locale: 'de-DE',
        form_source: 'studio',
        configuration_revision: INSTALLATION_REVISION,
        answers: ANSWERS,
      },
    });
  });

  it('sends installation feedback on the bundled form where the content language differs', async () => {
    expect(await sendThrough({ kind: 'public' }, 'en', ENGLISH)).toEqual({
      path: '/api/feedback',
      body: {
        audience: 'installation',
        locale: 'en',
        form_source: 'bundled',
        configuration_revision: null,
        answers: ANSWERS,
      },
    });
  });

  it('sends staff feedback from a conversation to the admin route with that session', async () => {
    expect(await sendThrough({ kind: 'staff', sessionId: 'E5F6G7H8' }, 'de', GERMAN)).toEqual({
      path: '/api/admin/feedback',
      body: {
        audience: 'staff',
        session_id: 'E5F6G7H8',
        locale: 'de-DE',
        form_source: 'studio',
        configuration_revision: KASSEL_REVISION,
        answers: ANSWERS,
      },
    });
  });

  it('gives an Arabic guest the bundled form, right to left, filed in Arabic', async () => {
    const sent = await sendThrough({ kind: 'guest', sessionId: 'A1B2C3D4' }, 'ar', ARABIC);

    expect(document.documentElement).toHaveAttribute('dir', 'rtl');
    expect(sent).toEqual({
      path: '/api/feedback',
      body: {
        audience: 'guest',
        session_id: 'A1B2C3D4',
        locale: 'ar',
        form_source: 'bundled',
        configuration_revision: null,
        answers: ANSWERS,
      },
    });
  });
});

function TwoOpeners() {
  const { openFeedback } = useFeedback();
  return (
    <>
      <button type="button" onClick={() => openFeedback({ kind: 'public' })}>
        open public
      </button>
      <button type="button" onClick={() => openFeedback({ kind: 'guest', sessionId: 'A1B2C3D4' })}>
        open guest
      </button>
    </>
  );
}

describe('reopening straight after a close', () => {
  const BUNDLED = 'Your ideas, feature requests, or anything that bothered you…';

  it('never shows the previous origin’s form to the new one', async () => {
    renderWithProviders(<TwoOpeners />, { services: { feedback: createStubFeedbackSink() } });

    await userEvent.click(screen.getByRole('button', { name: 'open public' }));
    await screen.findByPlaceholderText(BUNDLED);
    await userEvent.keyboard('{Escape}');
    // Well inside the 300 ms exit transition.
    await userEvent.click(screen.getByRole('button', { name: 'open guest', hidden: true }));

    expect(screen.queryByPlaceholderText(BUNDLED)).not.toBeInTheDocument();
    expect(await screen.findByPlaceholderText('Your ideas or complaints')).toBeInTheDocument();
  });

  it('keeps an answer given straight after reopening', async () => {
    renderWithProviders(<TwoOpeners />, { services: { feedback: createStubFeedbackSink() } });

    await userEvent.click(screen.getByRole('button', { name: 'open public' }));
    await screen.findByPlaceholderText(BUNDLED);
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'open public', hidden: true }));
    const quality = screen.getByRole('group', { name: 'Translation quality' });
    await userEvent.click(within(quality).getByRole('button', { name: '5 stars' }));
    await settled();

    expect(
      within(screen.getByRole('group', { name: 'Translation quality' })).getByRole('button', {
        name: '5 stars',
      })
    ).toHaveAttribute('aria-pressed', 'true');
  });
});
