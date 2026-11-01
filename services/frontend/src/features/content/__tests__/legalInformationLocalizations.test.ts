import { createElement } from 'react';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { CATALOGUES, createI18n, SUPPORTED_UI_LOCALES } from '@/i18n';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { renderWithProviders } from '@/test/renderWithProviders';

const keys = [
  'informationTitle',
  'informationNotice',
  'informationSource',
  'informationClose',
] as const;
const placeholders = (value: string) => (value.match(/{{\s*\w+\s*}}/g) ?? []).sort();

describe('legal information UI localization', () => {
  it.each(SUPPORTED_UI_LOCALES.filter((locale) => locale !== 'en'))(
    'translates the four UI strings into %s and preserves their interpolation',
    (locale) => {
      const copy = CATALOGUES[locale].legal;
      const instance = createI18n(locale);
      for (const key of keys) {
        expect(copy[key], `${locale}.${key}`).not.toBe(CATALOGUES.en.legal[key]);
        expect(placeholders(copy[key]), `${locale}.${key}`).toEqual(
          placeholders(CATALOGUES.en.legal[key])
        );
        expect(instance.t(`legal.${key}`, { locale: 'de-DE', version: 'source-42' })).not.toContain(
          '{{'
        );
      }
      expect(
        instance.t('legal.informationSource', { locale: 'de-DE', version: 'source-42' })
      ).toContain('de-DE');
      expect(
        instance.t('legal.informationSource', { locale: 'de-DE', version: 'source-42' })
      ).toContain('source-42');
    }
  );

  it('localizes the Arabic dialog UI while retaining the source body and its German language', async () => {
    const user = userEvent.setup();
    const copy = CATALOGUES.ar.legal;
    renderWithProviders(
      createElement(SiteLegalLinks, {
        information: {
          locale: 'de-DE',
          version: 'source-42',
          sections: [
            {
              id: 'mode2Consent',
              headline: 'Quellüberschrift',
              bodyHtml: '<p>Unveränderter Quelltext</p>',
            },
          ],
        },
      }),
      { locale: 'ar' }
    );
    await user.click(screen.getByRole('button', { name: copy.informationTitle }));
    const dialog = screen.getByRole('dialog', { name: copy.informationTitle });
    expect(within(dialog).getByText(copy.informationNotice)).toBeInTheDocument();
    const source = within(dialog).getByRole('region', { name: copy.informationTitle });
    expect(source).toHaveAttribute('lang', 'de-DE');
    expect(source).toHaveAttribute('dir', 'ltr');
    expect(within(source).getByText('Unveränderter Quelltext')).toBeInTheDocument();
    expect(within(source).getByRole('heading', { name: 'Quellüberschrift' })).toBeInTheDocument();
    expect(within(dialog).getByText(/de-DE/)).toHaveTextContent('source-42');
    expect(within(dialog).getByRole('button', { name: copy.informationClose })).toBeInTheDocument();
  });
});
