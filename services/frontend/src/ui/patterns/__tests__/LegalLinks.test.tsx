import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LegalLinks as LegalLinkUrls } from '@/domain/content/content.types';
import { LegalLinks } from '@/ui/patterns/LegalLinks';
import { renderWithProviders } from '@/test/renderWithProviders';
import { CATALOGUES } from '@/i18n';

const links: LegalLinkUrls = {
  imprintUrl: 'https://www.kassel.de/impressum.php',
  privacyPolicyUrl: 'https://www.kassel.de/datenschutzerklaerung.php',
  accessibilityStatementUrl: 'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php',
};

afterEach(() => {
  document.documentElement.dir = '';
});

describe('LegalLinks', () => {
  it('links imprint, privacy policy and accessibility statement in a new tab', () => {
    renderWithProviders(<LegalLinks links={links} />, { locale: 'de' });

    const nav = screen.getByRole('navigation', { name: 'Rechtliches' });
    const rendered = within(nav).getAllByRole('link');
    expect(rendered.map((link) => link.getAttribute('href'))).toEqual([
      links.imprintUrl,
      links.privacyPolicyUrl,
      links.accessibilityStatementUrl,
    ]);
    expect(rendered.map((link) => link.textContent)).toEqual([
      'Impressum (öffnet in neuem Tab)',
      'Datenschutz (öffnet in neuem Tab)',
      'Barrierefreiheit (öffnet in neuem Tab)',
    ]);
    for (const link of rendered) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  it('omits the accessibility statement when there is none', () => {
    renderWithProviders(<LegalLinks links={{ ...links, accessibilityStatementUrl: null }} />, {
      locale: 'de',
    });

    expect(screen.getAllByRole('link')).toHaveLength(2);
    expect(screen.queryByRole('link', { name: /Barrierefreiheit/ })).not.toBeInTheDocument();
  });

  it('renders nothing when there is no link at all', () => {
    const { container } = renderWithProviders(
      <LegalLinks
        links={{ imprintUrl: null, privacyPolicyUrl: null, accessibilityStatementUrl: null }}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('runs right to left in Arabic with translated labels', () => {
    renderWithProviders(<LegalLinks links={links} />, { locale: 'ar' });

    expect(document.documentElement).toHaveAttribute('dir', 'rtl');
    const nav = screen.getByRole('navigation', { name: 'معلومات قانونية' });
    expect(within(nav).getByRole('link', { name: /^بيانات الناشر/ })).toHaveAttribute(
      'href',
      links.imprintUrl
    );
    expect(within(nav).getByRole('list')).toHaveClass('justify-center');
  });

  it('uses the fixed dark ink on the always-white footer bar', () => {
    renderWithProviders(<LegalLinks links={links} tone="light" />);

    for (const link of screen.getAllByRole('link')) {
      expect(link).toHaveClass('text-black/60');
      expect(link).not.toHaveClass('text-fg-consent');
    }
  });

  // The conversation screens reserve a two-line band for this row
  // (--spacing-legal-band). 44 characters at 13px still wrap to two lines at
  // 320px; the long forms ("Политика конфиденциальности") needed three, and the
  // third line covered the mic buttons.
  it.each(Object.entries(CATALOGUES))(
    'keeps the %s labels short enough for two lines',
    (_, catalogue) => {
      const { imprint, privacyPolicy, accessibilityStatement } = catalogue.legal;

      expect(
        imprint.length + privacyPolicy.length + accessibilityStatement.length
      ).toBeLessThanOrEqual(44);
    }
  );
});
