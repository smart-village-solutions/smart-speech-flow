import { describe, expect, it } from 'vitest';
import type { ReviewerCandidate } from '@/domain/archive/archive.types';
import { covering } from '../useRequestVerification';

function candidate(sub: string, languages: string[]): ReviewerCandidate {
  const bytes = new Uint8Array(32);
  return {
    sub,
    displayName: sub,
    languages,
    sworn: false,
    keyVersion: 1,
    fingerprint: bytes,
    fingerprintDisplay: sub,
    encPub: bytes,
    sigPub: bytes,
  };
}

const subs = (found: readonly ReviewerCandidate[]) => found.map((each) => each.sub);

describe('covering', () => {
  it('keeps reviewers who speak every language of the conversation', () => {
    const both = candidate('both', ['de', 'tr']);
    const one = candidate('one', ['de']);
    expect(subs(covering([both, one], ['de', 'tr']))).toEqual(['both']);
  });

  it('counts a regional or differently cased tag from Studio as its language', () => {
    // Studio's competence languages are BCP 47 tags; a conversation names the bare language.
    const regional = candidate('regional', ['de', 'en-US', 'PT-br']);
    expect(subs(covering([regional], ['de', 'en', 'pt']))).toEqual(['regional']);
  });

  it('does not let a shared prefix stand for another language', () => {
    expect(subs(covering([candidate('enm', ['enm'])], ['en']))).toEqual([]);
  });

  it('keeps everyone for a conversation without languages', () => {
    expect(subs(covering([candidate('any', [])], []))).toEqual(['any']);
  });
});
