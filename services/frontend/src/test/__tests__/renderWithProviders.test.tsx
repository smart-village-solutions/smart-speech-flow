import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { toPublicContent } from '@/domain/content/content.mapper';
import type { ContentSource } from '@/domain/content/content.port';
import { usePublicContent } from '@/features/content/usePublicContent';
import { installationBody } from '@/test/contentFixtures';
import { renderWithProviders } from '@/test/renderWithProviders';

function Locale() {
  const { content, settled } = usePublicContent();
  return <output>{settled ? (content?.locale ?? 'bundled') : 'pending'}</output>;
}

const reject = () => Promise.reject(new Error('unused'));

describe('renderWithProviders', () => {
  it('starts with installation content, as screens have it once the gate opens', () => {
    renderWithProviders(<Locale />);

    expect(screen.getByRole('status')).toHaveTextContent('de-DE');
  });

  it('lets an overridden content source answer instead of the seed', async () => {
    const content: ContentSource = {
      getPublic: async () => ({ ...toPublicContent(installationBody), locale: 'en-GB' }),
      getGuestLanguages: reject,
      getGuest: reject,
      getStaff: reject,
    };

    renderWithProviders(<Locale />, { services: { content } });

    expect(await screen.findByText('en-GB')).toBeInTheDocument();
  });
});
