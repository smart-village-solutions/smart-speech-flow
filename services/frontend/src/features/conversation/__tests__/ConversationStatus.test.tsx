import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConversationStatus } from '@/features/conversation/ConversationStatus';
import { hasConversationStatus } from '@/features/conversation/conversation.status';

const quiet = {
  ended: false,
  connection: 'connected' as const,
  hasConnected: true,
  errorKey: null,
  onRetry: null,
};

describe('ConversationStatus', () => {
  it('says nothing at all while the conversation is healthy', () => {
    const { container } = renderWithProviders(<ConversationStatus {...quiet} />);

    expect(container).toBeEmptyDOMElement();
    expect(hasConversationStatus(quiet)).toBe(false);
  });

  it('stays quiet during the very first connect, which is not a reconnect', () => {
    const opening = { ...quiet, connection: 'connecting' as const, hasConnected: false };

    const { container } = renderWithProviders(<ConversationStatus {...opening} />);

    expect(container).toBeEmptyDOMElement();
    expect(hasConversationStatus(opening)).toBe(false);
  });

  it('reports a dropped connection once one has been made', () => {
    const dropped = { ...quiet, connection: 'disconnected' as const };

    renderWithProviders(<ConversationStatus {...dropped} />);

    expect(screen.getByRole('status')).toHaveTextContent('Reconnecting…');
    expect(hasConversationStatus(dropped)).toBe(true);
  });

  it('gives a failed send an alert and a way out', async () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <ConversationStatus {...quiet} errorKey="conversation.sendFailed" onRetry={onRetry} />
    );

    expect(screen.getByRole('alert')).toHaveTextContent('That message could not be sent.');

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('omits the retry control when there is nothing to retry', () => {
    renderWithProviders(<ConversationStatus {...quiet} errorKey="conversation.sendFailed" />);

    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('reports the end of the conversation above a dropped connection', () => {
    renderWithProviders(
      <ConversationStatus {...quiet} ended connection="disconnected" />
    );

    // A finished conversation has no connection to worry about.
    expect(screen.getByRole('status')).toHaveTextContent('This conversation has ended.');
    expect(screen.getByRole('status')).not.toHaveTextContent('Reconnecting');
  });

  it('dresses every message as a pill rather than bare floating text', () => {
    const { container } = renderWithProviders(
      <ConversationStatus {...quiet} connection="disconnected" />
    );

    const pill = container.querySelector('[data-status-pill]');
    expect(pill).not.toBeNull();
    expect(pill?.className).toContain('rounded-pill');
    expect(pill?.className).toContain('bg-surface-status');
    expect(pill?.className).toContain('border');
  });
});
