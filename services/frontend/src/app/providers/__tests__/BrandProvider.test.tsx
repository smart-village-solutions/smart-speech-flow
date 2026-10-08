import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { BrandProvider } from '@/app/providers/BrandProvider';
import { I18nProvider } from '@/app/providers/I18nProvider';
import { useBrand } from '@/app/providers/brand';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';

function Probe() {
  const { brand, displayName, legal, toggleBrand } = useBrand();
  return (
    <button type="button" onClick={toggleBrand}>
      {brand}:{displayName}:{legal.imprintUrl ?? 'no imprint'}
    </button>
  );
}

afterEach(() => {
  delete document.documentElement.dataset.brand;
});

describe('BrandProvider', () => {
  it('starts on the source default and stamps the html element', () => {
    render(
      <I18nProvider locale="de">
        <BrandProvider source={createStaticBrandSource('ssf')}>
          <Probe />
        </BrandProvider>
      </I18nProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('ssf:KasselDIALOG:no imprint');
    expect(document.documentElement).toHaveAttribute('data-brand', 'ssf');
  });

  it('cycles to the next brand', async () => {
    render(
      <I18nProvider locale="de">
        <BrandProvider source={createStaticBrandSource('ssf')}>
          <Probe />
        </BrandProvider>
      </I18nProvider>
    );

    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByRole('button')).toHaveTextContent(
      'kassel:KasselDIALOG:https://www.kassel.de/impressum.php'
    );
    expect(document.documentElement).toHaveAttribute('data-brand', 'kassel');
  });
});
