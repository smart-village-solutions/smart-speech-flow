import { describe, expect, it } from 'vitest';
import { range } from '@/lib/range';

describe('range', () => {
  it('includes both ends', () => {
    expect(range(0, 3)).toEqual([0, 1, 2, 3]);
  });

  it('is empty when the bounds are reversed', () => {
    expect(range(5, 1)).toEqual([]);
  });
});
