import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ContentSettled } from '@/test/ContentSettled';
import { installationBody } from '@/test/contentFixtures';
import { plainHttp } from '@/test/plainHttp';

const KASSEL = [
  'https://www.kassel.de/impressum.php',
  'https://www.kassel.de/datenschutzerklaerung.php',
  'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php',
];

function hrefs(): (string | null)[] {
  const nav = screen.getByRole('navigation', { name: 'Legal information' });
  return within(nav)
    .getAllByRole('link')
    .map((link) => link.getAttribute('href'));
}

async function renderFetched(brand: 'ssf' | 'kassel') {
  renderWithProviders(
    <>
      <SiteLegalLinks />
      <ContentSettled />
    </>,
    { brand, publicContent: 'fetched' }
  );
  await screen.findByTestId('public-content-settled');
}

describe('SiteLegalLinks', () => {
  it("shows Studio's links", () => {
    renderWithProviders(<SiteLegalLinks />);

    expect(hrefs()).toEqual(KASSEL);
  });

  it('falls back to the Kassel bundle when installation content is unavailable (503)', async () => {
    server.use(
      http.get('*/api/content/installation', () =>
        HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
      )
    );

    await renderFetched('kassel');

    expect(hrefs()).toEqual(KASSEL);
  });

  it('shows no links for the neutral brand without installation content', async () => {
    server.use(http.get('*/api/content/installation', () => HttpResponse.error()));

    await renderFetched('ssf');

    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('replaces a non-https imprint with the bundled one and keeps the rest', async () => {
    server.use(
      http.get('*/api/content/installation', () =>
        HttpResponse.json({
          ...installationBody,
          legal: {
            ...installationBody.legal,
            imprintUrl: plainHttp('https://studio.example/impressum'),
            privacyPolicyUrl: 'https://studio.example/datenschutz',
          },
        })
      )
    );

    await renderFetched('kassel');

    expect(hrefs()).toEqual([KASSEL[0], 'https://studio.example/datenschutz', KASSEL[2]]);
  });
});
