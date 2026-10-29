import { useState } from 'react';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { ReviewActions } from '@/features/recovery/ReviewActions';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

const r = de.admin.recovery;

/** Serves one fingerprint, then another, as a refetch with swapped keys would. */
function Swapping() {
  const [fill, setFill] = useState(1);
  return (
    <>
      <button type="button" onClick={() => setFill(2)}>
        swap
      </button>
      <ReviewActions
        fingerprint={new Uint8Array(32).fill(fill)}
        keys={{} as UnlockedKeys}
        pending={false}
        onApprove={vi.fn()}
        onDecline={vi.fn()}
        onOpenKeys={vi.fn()}
      />
    </>
  );
}

describe('ReviewActions', () => {
  it('a tick holds its fingerprint: another value reads as unticked and cannot be approved', async () => {
    renderWithProviders(<Swapping />, { locale: 'de' });
    await userEvent.click(screen.getByLabelText(r.approve.confirmed));
    expect(screen.getByRole('button', { name: r.approve.action })).toBeEnabled();

    await userEvent.click(screen.getByRole('button', { name: 'swap' }));

    expect(screen.getByLabelText(r.approve.confirmed)).not.toBeChecked();
    expect(screen.getByRole('button', { name: r.approve.action })).toBeDisabled();
  });
});
