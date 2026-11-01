import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { StatusChip } from '@/ui/primitives/StatusChip';
import { InlineAlert } from '@/ui/patterns/InlineAlert';
import { EmptyState } from '@/ui/patterns/EmptyState';

describe('shared feedback patterns', () => {
  it.each(['neutral', 'success', 'warning', 'danger'] as const)(
    'keeps the %s status readable as text without unsolicited announcements',
    (tone) => {
      render(<StatusChip tone={tone}>Translation available</StatusChip>);
      expect(screen.getByText('Translation available')).toBeVisible();
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    }
  );

  it('announces a failure and retains its recovery action', async () => {
    const retry = vi.fn();
    render(
      <InlineAlert tone="danger" title="Could not save">
        Your answer is preserved. <button onClick={retry}>Retry</button>
      </InlineAlert>
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it('allows a static notice to opt out of live announcements', () => {
    render(<InlineAlert tone="warning" title="Scheduled maintenance" role="note" />);
    expect(screen.getByRole('note')).toHaveTextContent('Scheduled maintenance');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('supports an empty state with a named heading, description and optional action', async () => {
    const create = vi.fn();
    render(
      <EmptyState
        title="No conversations"
        description="New conversations will appear here."
        action={<button onClick={create}>Start conversation</button>}
      />
    );
    expect(screen.getByRole('heading', { name: 'No conversations' })).toBeVisible();
    expect(screen.getByText('New conversations will appear here.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    expect(create).toHaveBeenCalledOnce();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
