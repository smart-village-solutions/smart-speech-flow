import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useFeedback } from '@/app/providers/feedback';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';

/**
 * The provider sits above <Routes>, so useParams cannot reach a session here.
 * Whatever the caller knows has to travel with the call that opens the sheet.
 */
function Opener({ sessions }: Readonly<{ sessions: (string | null)[] }>) {
  const { openFeedback } = useFeedback();

  return (
    <>
      {sessions.map((session) => (
        <button key={String(session)} type="button" onClick={() => openFeedback(session)}>
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

/**
 * Closing resets the form 300ms later, after the exit transition (export 146).
 * Refilling before that lands wipes the ratings mid-test and mid-use alike.
 */
function settled() {
  return new Promise((resolve) => {
    setTimeout(resolve, 350);
  });
}

async function submitTheForm() {
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
