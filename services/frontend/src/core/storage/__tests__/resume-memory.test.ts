import { describe, expect, it } from 'vitest';
import { createResumeMemory } from '@/core/storage/resume-memory';

describe('resume memory', () => {
  it('returns a remembered view once', () => {
    const memory = createResumeMemory(() => globalThis.sessionStorage);
    memory.remember('keys');
    expect(memory.take()).toBe('keys');
    expect(memory.take()).toBeNull();
  });

  it('degrades to nothing when storage is refused', () => {
    const memory = createResumeMemory(() => {
      throw new Error('SecurityError');
    });
    expect(() => memory.remember('keys')).not.toThrow();
    expect(memory.take()).toBeNull();
  });
});
