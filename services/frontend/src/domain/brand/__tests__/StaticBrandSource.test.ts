import { describe, expect, it } from 'vitest';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';

describe('createStaticBrandSource', () => {
  it('lists both brands', () => {
    expect(
      createStaticBrandSource('ssf')
        .list()
        .map((brand) => brand.id)
    ).toEqual(['ssf', 'kassel']);
  });

  it('returns the configured default', () => {
    expect(createStaticBrandSource('kassel').getDefault()).toBe('kassel');
  });

  it('bundles Kassel legal links and none for the neutral brand', () => {
    const [ssf, kassel] = createStaticBrandSource('ssf').list();

    expect(ssf.legal).toEqual({
      imprintUrl: null,
      privacyPolicyUrl: null,
      accessibilityStatementUrl: null,
    });
    expect(kassel.legal).toEqual({
      imprintUrl: 'https://www.kassel.de/impressum.php',
      privacyPolicyUrl: 'https://www.kassel.de/datenschutzerklaerung.php',
      accessibilityStatementUrl: 'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php',
    });
  });
});
