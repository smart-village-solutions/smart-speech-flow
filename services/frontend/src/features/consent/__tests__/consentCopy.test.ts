import { describe, expect, it } from 'vitest';
import { consentCopy } from '@/features/consent/consentCopy';
import type { GuestContent } from '@/domain/content/content.types';

function provided(explanationHtml: string): GuestContent {
  return {
    provided: true,
    revision: 'sha256:r',
    explanationHtml,
    feedback: null,
  };
}

describe('consentCopy', () => {
  it("uses Studio's explanation", () => {
    expect(consentCopy(provided('<p>Explanation</p>'))).toEqual({
      explanationHtml: '<p>Explanation</p>',
    });
  });

  it('keeps the bundled texts for a language Studio does not provide, or without content', () => {
    expect(consentCopy({ provided: false })).toEqual({ explanationHtml: undefined });
    expect(consentCopy(undefined)).toEqual({ explanationHtml: undefined });
  });

  it('falls back when Studio markup has no text', () => {
    expect(consentCopy(provided('<p> </p>'))).toEqual({ explanationHtml: undefined });
  });
});
