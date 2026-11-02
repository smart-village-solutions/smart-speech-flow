import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { KeyVault, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { ReviewRepository } from '@/domain/review/review.repository';
import { ReviewScreen } from '@/features/review/ReviewScreen';
import { ReviewsScreen } from '@/features/review/ReviewsScreen';
import { useReview } from '@/features/review/useReviews';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/features/review/useReviews', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/review/useReviews')>()),
  useReview: vi.fn(),
}));

const r = de.admin.review;

function vault(keys: UnlockedKeys | null): KeyVault {
  return { current: () => keys, hold: vi.fn(), lock: vi.fn(), subscribe: () => () => undefined };
}

describe('ReviewsScreen', () => {
  it('asks for the key before listing anything', async () => {
    const onOpenKeys = vi.fn();
    renderWithProviders(
      <ReviewsScreen onBack={vi.fn()} onOpenKeys={onOpenKeys} onSignOut={vi.fn()} />,
      {
        locale: 'de',
        services: {
          keyVault: vault(null),
          reviews: { inbox: vi.fn() } as unknown as ReviewRepository,
        },
      }
    );
    await userEvent.click(screen.getByRole('button', { name: r.unlock }));
    expect(onOpenKeys).toHaveBeenCalled();
    expect(screen.queryByText(r.empty)).not.toBeInTheDocument();
  });

  it('lists assignments once the key is open', async () => {
    renderWithProviders(
      <ReviewsScreen onBack={vi.fn()} onOpenKeys={vi.fn()} onSignOut={vi.fn()} />,
      {
        locale: 'de',
        services: {
          keyVault: vault({} as UnlockedKeys),
          reviews: { inbox: vi.fn().mockResolvedValue([]) } as unknown as ReviewRepository,
        },
      }
    );
    expect(await screen.findByText(r.empty)).toBeInTheDocument();
  });
});

describe('ReviewScreen', () => {
  it('shows only the check while it runs and only the error when it fails', () => {
    vi.mocked(useReview).mockReturnValue({ status: 'checking' });
    const { rerender } = renderWithProviders(
      <ReviewScreen verificationId="v-1" unlocked={{} as UnlockedKeys} onDone={vi.fn()} />,
      { locale: 'de' }
    );
    expect(screen.getByText(de.admin.archive.checking)).toBeInTheDocument();
    vi.mocked(useReview).mockReturnValue({ status: 'broken', stage: 'wrap' });
    rerender(<ReviewScreen verificationId="v-1" unlocked={{} as UnlockedKeys} onDone={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent(de.admin.archive.integrity.wrap);
    vi.mocked(useReview).mockReturnValue({ status: 'unavailable' });
    rerender(<ReviewScreen verificationId="v-1" unlocked={{} as UnlockedKeys} onDone={vi.fn()} />);
    expect(screen.getByRole('alert')).toHaveTextContent(r.unavailable);
  });
});
