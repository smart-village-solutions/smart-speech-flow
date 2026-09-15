import { useState } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';
import { AppError } from '@/core/http/AppError';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import type { FeedbackSink } from '@/domain/feedback/feedback.port';
import type { FeedbackSubmission } from '@/domain/feedback/feedback.types';

const PLACEHOLDER = 'Your ideas, feature requests, or anything that bothered you…';

function open(recorded = vi.fn()) {
  renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
    services: { feedback: createStubFeedbackSink(recorded) },
  });
  return recorded;
}

/** A sink whose outcome each test decides, so the intermediate state is observable. */
function controllable() {
  const calls: FeedbackSubmission[] = [];
  let settle: (() => void) | null = null;
  let fail: ((error: unknown) => void) | null = null;

  const sink: FeedbackSink = {
    submit(submission) {
      calls.push(submission);
      return new Promise<void>((resolve, reject) => {
        settle = () => resolve();
        fail = reject;
      });
    },
  };

  return {
    sink,
    calls,
    succeed: () => settle?.(),
    reject: (error: unknown) => fail?.(error),
  };
}

async function completeAllRatings() {
  for (const label of ['Translation quality', 'Performance', 'UI / UX']) {
    const group = screen.getByRole('group', { name: label });
    await userEvent.click(within(group).getByRole('button', { name: '5 stars' }));
  }
  await userEvent.click(screen.getByRole('button', { name: 'Score 9' }));
}

const submitButton = () => screen.getByRole('button', { name: /Send feedback|Send again|Sending/ });

/** The sheet with its own open state, so a close and a reopen are observable. */
function Reopenable() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        reopen
      </button>
      <FeedbackSheet open={open} onOpenChange={setOpen} />
    </>
  );
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe('FeedbackSheet', () => {
  it('renders all five sections', () => {
    open();

    expect(screen.getByRole('dialog', { name: 'Share your feedback' })).toBeInTheDocument();
    expect(screen.getByText('Translation quality')).toBeInTheDocument();
    expect(screen.getByText('Performance')).toBeInTheDocument();
    expect(screen.getByText('UI / UX')).toBeInTheDocument();
    expect(screen.getByText('Recommendation')).toBeInTheDocument();
    expect(screen.getByText('Improvement ideas')).toBeInTheDocument();
  });

  it('keeps submit disabled until all three ratings and the score are set', async () => {
    open();

    expect(submitButton()).toBeDisabled();

    await completeAllRatings();

    expect(submitButton()).toBeEnabled();
  });

  it('submits the collected values through the sink', async () => {
    const recorded = open();

    await completeAllRatings();
    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), 'more languages');
    await userEvent.click(submitButton());

    await waitFor(() =>
      expect(recorded).toHaveBeenCalledWith({
        translationQuality: 5,
        performance: 5,
        usability: 5,
        netPromoterScore: 9,
        improvements: 'more languages',
        sessionId: null,
      })
    );
  });

  it('shows the thank-you state after submitting', async () => {
    open();

    await completeAllRatings();
    await userEvent.click(submitButton());

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
  });

  it('shows the processing notice beside the submit action', () => {
    // Article 13 information has to be readable at the moment of submission,
    // not behind a link or a scroll away from the button.
    open();

    expect(
      screen.getByText('Your answers are used only to improve Smart Speech Flow.')
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'We keep feedback for twelve months and delete it automatically after that.'
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'You can have your feedback withdrawn at any time — just ask a member of staff.'
      )
    ).toBeInTheDocument();
  });

  it('does not thank anyone until the service has accepted', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());

    expect(screen.queryByText('Thank you!')).not.toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(submitButton()).toHaveAttribute('aria-busy', 'true');

    controlled.succeed();

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
  });

  it('submits once however often the button is pressed', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    await userEvent.click(submitButton());

    expect(controlled.calls).toHaveLength(1);
  });

  it('keeps every entered value when submission fails', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), 'more languages');
    await userEvent.click(submitButton());
    controlled.reject(new AppError('server', { status: 503 }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your feedback could not be sent. Your answers have been kept.'
    );
    expect(screen.getByPlaceholderText(PLACEHOLDER)).toHaveValue('more languages');
    for (const label of ['Translation quality', 'Performance', 'UI / UX']) {
      const group = screen.getByRole('group', { name: label });
      expect(within(group).getByRole('button', { name: '5 stars' })).toHaveAttribute(
        'aria-pressed',
        'true'
      );
    }
    expect(screen.getByRole('button', { name: 'Score 9' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('explains the failure with the reason the client normalised', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('network'));

    expect(await screen.findByRole('alert')).toHaveTextContent('No connection to the server.');
  });

  it('falls back to the generic reason for anything that is not an AppError', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new TypeError('boom'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.');
  });

  it('retries the preserved submission and reaches the thank-you state', async () => {
    let attempts = 0;
    const sink: FeedbackSink = {
      submit: async (submission) => {
        attempts += 1;
        if (attempts === 1) {
          throw new AppError('server', { status: 503 });
        }
        expect(submission.improvements).toBe('more languages');
      },
    };
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, { services: { feedback: sink } });

    await completeAllRatings();
    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), 'more languages');
    await userEvent.click(submitButton());

    await userEvent.click(await screen.findByRole('button', { name: /Send again/ }));

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it('clears the failure once a retry is under way', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('server', { status: 503 }));
    await screen.findByRole('alert');

    await userEvent.click(screen.getByRole('button', { name: /Send again/ }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('limits the improvement text to the length the Gateway accepts', () => {
    open();

    expect(screen.getByPlaceholderText(PLACEHOLDER)).toHaveAttribute('maxlength', '4000');
  });

  // Closing mid-submit, at both timings that matter. The reset is deferred
  // 300ms for the exit animation, so a result can land on either side of it
  // and the outcome must not depend on which.
  it.each([
    ['before the deferred reset', 120],
    ['after the deferred reset', 400],
  ])('discards a success that lands %s', async (_name, delay) => {
    const controlled = controllable();
    renderWithProviders(<Reopenable />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await wait(delay);
    controlled.succeed();
    await wait(400);

    await userEvent.click(screen.getByRole('button', { name: 'reopen' }));

    expect(screen.queryByText('Thank you!')).not.toBeInTheDocument();
    expect(submitButton()).toBeInTheDocument();
  });

  it.each([
    ['before the deferred reset', 120],
    ['after the deferred reset', 400],
  ])('discards a failure that lands %s', async (_name, delay) => {
    const controlled = controllable();
    renderWithProviders(<Reopenable />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await wait(delay);
    controlled.reject(new AppError('network'));
    await wait(400);

    await userEvent.click(screen.getByRole('button', { name: 'reopen' }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it('offers a retry when sending again could work', async () => {
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('network'));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(submitButton()).toBeEnabled();
  });

  it('does not offer a retry the server has already refused', async () => {
    // An unknown session is a defined rejection (#302), not a transient fault.
    // The same payload would be refused identically every time, so a Retry
    // here is a loop that cannot terminate.
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('notFound', { status: 404 }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('That was not found.')).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it('still offers a retry when the server only throttled the request', async () => {
    // 429 carries Retry-After: the server is asking for exactly one more
    // attempt later. Bucketing it with the terminal 4xx would disable the
    // button for a throttle and show "could not be processed" for a wait.
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('validation', { status: 429 }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(submitButton()).toBeEnabled();
  });

  it('lets the form be edited back into a submittable state after a refusal', async () => {
    // A session that timed out answers 404, which is terminal for that
    // payload. Leaving the button dead for the life of the sheet means the
    // only way out is Close, which discards every rating the user entered.
    const controlled = controllable();
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      services: { feedback: controlled.sink },
    });

    await completeAllRatings();
    await userEvent.click(submitButton());
    controlled.reject(new AppError('notFound', { status: 404 }));

    await waitFor(() => expect(submitButton()).toBeDisabled());

    const group = screen.getByRole('group', { name: 'Performance' });
    await userEvent.click(within(group).getByRole('button', { name: '4 stars' }));

    expect(submitButton()).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
