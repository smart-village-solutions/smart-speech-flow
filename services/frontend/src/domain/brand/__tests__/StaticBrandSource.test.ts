import { describe, expect, it } from 'vitest';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';

describe('createStaticBrandSource', () => {
  it('lists both brands', () => {
    expect(createStaticBrandSource('ssf').list()).toEqual([
      { id: 'ssf', displayName: 'Smart Speech Flow' },
      { id: 'kassel', displayName: 'Kassel Dialog' },
    ]);
  });

  it('returns the configured default', () => {
    expect(createStaticBrandSource('kassel').getDefault()).toBe('kassel');
  });
});
