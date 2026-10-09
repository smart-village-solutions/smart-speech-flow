import { describe, expect, it } from 'vitest';
import { consentCopy } from '@/features/consent/consentCopy';
import type { GuestContent, StorageMode } from '@/domain/content/content.types';

function provided(mode: StorageMode, overrides: Partial<GuestContent> = {}): GuestContent {
  return {
    storage: { mode },
    provided: true,
    revision: 'sha256:r',
    explanationHtml: '<p>Explanation</p>',
    storageQuestionHtml: mode === 'disabled' ? null : '<p>Question</p>',
    feedback: null,
    ...overrides,
  } as GuestContent;
}

describe('consentCopy', () => {
  it("uses Studio's texts and asks when the mode is ask", () => {
    expect(consentCopy(provided('ask'))).toEqual({
      explanationHtml: '<p>Explanation</p>',
      asksStorage: true,
      questionHtml: '<p>Question</p>',
    });
  });

  it.each<StorageMode>(['disabled', 'unknown'])('asks nothing when the mode is %s', (mode) => {
    const copy = consentCopy(provided(mode));
    expect(copy.asksStorage).toBe(false);
    expect(copy.explanationHtml).toBe('<p>Explanation</p>');
  });

  it('keeps the bundled texts for a language Studio does not provide, following the mode', () => {
    expect(consentCopy({ storage: { mode: 'ask' }, provided: false })).toEqual({
      explanationHtml: undefined,
      asksStorage: true,
      questionHtml: undefined,
    });
    expect(consentCopy({ storage: { mode: 'disabled' }, provided: false }).asksStorage).toBe(false);
  });

  it('treats missing content as bundled, with nothing asked, because the mode is unknown', () => {
    expect(consentCopy(undefined)).toEqual({
      explanationHtml: undefined,
      asksStorage: false,
      questionHtml: undefined,
    });
  });

  it('falls back field by field when Studio markup has no text', () => {
    expect(
      consentCopy(provided('ask', { explanationHtml: '<p> </p>', storageQuestionHtml: '<p></p>' }))
    ).toEqual({ explanationHtml: undefined, asksStorage: true, questionHtml: undefined });
  });
});
