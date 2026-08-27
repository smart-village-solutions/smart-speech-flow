import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';

function open(recorded = vi.fn()) {
  renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
    services: { feedback: createStubFeedbackSink(recorded) },
  });
  return recorded;
}

async function completeAllRatings() {
  for (const label of ['Translation quality', 'Performance', 'UI / UX']) {
    const group = screen.getByRole('group', { name: label });
    await userEvent.click(within(group).getByRole('button', { name: '5 stars' }));
  }
  await userEvent.click(screen.getByRole('button', { name: 'Score 9' }));
}

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

    expect(screen.getByRole('button', { name: /Send feedback/ })).toBeDisabled();

    await completeAllRatings();

    expect(screen.getByRole('button', { name: /Send feedback/ })).toBeEnabled();
  });

  it('submits the collected values through the sink', async () => {
    const recorded = open();

    await completeAllRatings();
    await userEvent.type(
      screen.getByPlaceholderText('Your ideas, feature requests, or anything that bothered you…'),
      'more languages'
    );
    await userEvent.click(screen.getByRole('button', { name: /Send feedback/ }));

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
    await userEvent.click(screen.getByRole('button', { name: /Send feedback/ }));

    expect(await screen.findByText('Thank you!')).toBeInTheDocument();
  });
});
