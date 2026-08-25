import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useTranslation } from 'react-i18next';
import { I18nProvider } from '../I18nProvider';

function Probe() {
  const { t } = useTranslation();
  return <p>{t('language.title')}</p>;
}

function renderAt(locale: string) {
  return render(
    <I18nProvider locale={locale}>
      <Probe />
    </I18nProvider>
  );
}

describe('I18nProvider', () => {
  it('renders in the locale it is given', () => {
    renderAt('en');
    expect(screen.getByText('Choose your language')).toBeInTheDocument();
  });

  it('follows the locale when it changes', () => {
    const { rerender } = renderAt('de');
    expect(screen.getByText('Wählen Sie Ihre Sprache')).toBeInTheDocument();

    rerender(
      <I18nProvider locale="tr">
        <Probe />
      </I18nProvider>
    );
    expect(screen.getByText('Dilinizi seçin')).toBeInTheDocument();
  });

  // Screen readers and the browser's own hyphenation and quotation rules key
  // off `lang`; the layout keys off `dir`.
  it('stamps the language and direction on the document element', () => {
    renderAt('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('turns the document right to left for Arabic', () => {
    renderAt('ar');
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('turns the document back to left to right when the locale changes away', () => {
    const { rerender } = renderAt('fa');
    expect(document.documentElement.dir).toBe('rtl');

    rerender(
      <I18nProvider locale="uk">
        <Probe />
      </I18nProvider>
    );
    expect(document.documentElement.dir).toBe('ltr');
    expect(document.documentElement.lang).toBe('uk');
  });
});
