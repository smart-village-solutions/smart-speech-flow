import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { BrandProvider } from '@/app/providers/BrandProvider';
import { useBrand } from '@/app/providers/brand';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';

function Probe() {
  const { brand, displayName, toggleBrand } = useBrand();
  return (
    <button type="button" onClick={toggleBrand}>
      {brand}:{displayName}
    </button>
  );
}

afterEach(() => {
  delete document.documentElement.dataset.brand;
});

describe('BrandProvider', () => {
  it('starts on the source default and stamps the html element', () => {
    render(
      <BrandProvider source={createStaticBrandSource('ssf')}>
        <Probe />
      </BrandProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('ssf:Smart Speech Flow');
    expect(document.documentElement).toHaveAttribute('data-brand', 'ssf');
  });

  it('cycles to the next brand', async () => {
    render(
      <BrandProvider source={createStaticBrandSource('ssf')}>
        <Probe />
      </BrandProvider>
    );

    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByRole('button')).toHaveTextContent('kassel:Kassel Dialog');
    expect(document.documentElement).toHaveAttribute('data-brand', 'kassel');
  });
});
