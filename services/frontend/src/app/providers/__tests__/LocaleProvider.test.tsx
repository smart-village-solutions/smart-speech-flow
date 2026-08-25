import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LocaleProvider } from '../LocaleProvider';
import { useLocale, useScreenLocale } from '../locale';

function Readout() {
  const { locale } = useLocale();
  return <p data-testid="locale">{locale}</p>;
}

function Screen({ declares }: { declares: string }) {
  useScreenLocale(declares);
  return <Readout />;
}

describe('LocaleProvider', () => {
  it('starts on the locale it was given', () => {
    render(
      <LocaleProvider initialLocale="de">
        <Readout />
      </LocaleProvider>
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('de');
  });

  it('moves to the locale a screen declares', () => {
    render(
      <LocaleProvider initialLocale="de">
        <Screen declares="ar" />
      </LocaleProvider>
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('ar');
  });

  // The conversation screen declares nothing until its session query resolves.
  it('holds the current locale while a screen has nothing to declare', () => {
    render(
      <LocaleProvider initialLocale="tr">
        <Screen declares="" />
      </LocaleProvider>
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('tr');
  });

  it('ignores a language the UI has no catalogue for', () => {
    render(
      <LocaleProvider initialLocale="en">
        <Screen declares="zz" />
      </LocaleProvider>
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('en');
  });

  it('refuses to work outside a provider', () => {
    expect(() => render(<Readout />)).toThrow(/LocaleProvider/);
  });
});
