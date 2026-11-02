import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReviewRepository } from '@/domain/review/review.repository';
import type { InboxRow } from '@/domain/review/review.types';
import { ReviewInbox } from '@/features/review/ReviewInbox';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

const r = de.admin.review;

function row(id: string, status: InboxRow['status'], openable: boolean): InboxRow {
  return {
    verificationId: id,
    status,
    requestedAt: '2026-11-02T10:00:00+00:00',
    requestedBy: 'alice',
    startedAt: '2026-10-29T10:00:00+00:00',
    endedAt: '2026-10-29T10:20:00+00:00',
    messages: 3,
    openable,
  };
}

function render(rows: InboxRow[] | Error) {
  const onOpen = vi.fn();
  const inbox =
    rows instanceof Error ? vi.fn().mockRejectedValue(rows) : vi.fn().mockResolvedValue(rows);
  renderWithProviders(<ReviewInbox onOpen={onOpen} />, {
    locale: 'de',
    services: { reviews: { inbox } as unknown as ReviewRepository },
  });
  return onOpen;
}

describe('ReviewInbox', () => {
  it('opens an open assignment and leaves closed or unreadable rows inert', async () => {
    const onOpen = render([
      row('v-1', 'awaiting', true),
      row('v-2', 'in_review', false),
      row('v-3', 'approved', false),
    ]);
    await userEvent.click(
      await screen.findByRole('button', { name: new RegExp(r.status.awaiting) })
    );
    expect(onOpen).toHaveBeenCalledWith('v-1');
    expect(screen.getAllByRole('button')).toHaveLength(1);
    // Only an open record whose conversation is gone reads "closed"; a decided one says how.
    expect(screen.getAllByText(r.status.closed)).toHaveLength(1);
    expect(screen.getByText(r.status.approved)).toBeInTheDocument();
  });

  it('says when nothing is assigned, and when the list cannot be read', async () => {
    render([]);
    expect(await screen.findByText(r.empty)).toBeInTheDocument();
  });

  it('reports a failed read', async () => {
    render(new Error('down'));
    expect(await screen.findByRole('alert')).toHaveTextContent(r.unavailable);
  });
});
