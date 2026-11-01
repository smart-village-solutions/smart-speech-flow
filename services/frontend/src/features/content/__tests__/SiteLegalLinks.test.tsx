import userEvent from '@testing-library/user-event';
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
            accessibilityStatementUrl: 'https://studio.example/barrierefreiheit',
          },
        })
      )
    );

    await renderFetched('kassel');

    expect(hrefs()).toEqual([
      KASSEL[0],
      'https://studio.example/datenschutz',
      'https://studio.example/barrierefreiheit',
    ]);
  });
});

it('opens safe source wording as information with only a close action and restores focus', async () => {
  const user = userEvent.setup();
  renderWithProviders(
    <SiteLegalLinks
      information={{
        locale: 'de-DE',
        version: 'studio-source-42',
        sections: [
          {
            id: 'mode2Consent',
            headline: 'Source heading',
            bodyHtml:
              '<p>Source <strong>wording</strong></p><script>unsafeScript()</script><a href="javascript:bad()">unsafe link</a>',
          },
        ],
      }}
    />
  );
  const trigger = screen.getByRole('button', { name: 'Consent and recording terms' });
  expect(trigger).toHaveClass('pointer-events-auto');
  await user.click(trigger);
  const dialog = screen.getByRole('dialog', { name: 'Consent and recording terms' });
  expect(
    within(dialog).getByText(
      'This view is for information only. You do not give consent or authorize recording here.'
    )
  ).toBeInTheDocument();
  expect(within(dialog).getByText(/de-DE/)).toBeInTheDocument();
  expect(within(dialog).getByText(/studio-source-42/)).toBeInTheDocument();
  expect(within(dialog).getByRole('heading', { name: 'Source heading' })).toBeInTheDocument();
  const wording = within(dialog).getByRole('region', { name: 'Consent and recording terms' });
  expect(wording).toHaveAttribute('tabindex', '0');
  expect(wording).toHaveAttribute('lang', 'de-DE');
  expect(wording).toHaveAttribute('dir', 'ltr');
  expect(dialog.querySelector('strong')).toHaveTextContent('wording');
  expect(dialog.querySelector('script')).toBeNull();
  expect(within(dialog).queryByRole('link')).not.toBeInTheDocument();
  expect(within(dialog).queryByRole('checkbox')).not.toBeInTheDocument();
  expect(within(dialog).getAllByRole('button')).toHaveLength(1);
  await user.click(within(dialog).getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
