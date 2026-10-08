import { describe, expect, it } from 'vitest';
import { toPublicContent } from '@/domain/content/content.mapper';
import type { LegalLinks } from '@/domain/content/content.types';
import { resolveLegalLinks } from '@/features/content/legalLinks';
import { installationBody } from '@/test/contentFixtures';

const bundled: LegalLinks = {
  imprintUrl: 'https://bundled.example/imprint',
  privacyPolicyUrl: 'https://bundled.example/privacy',
  accessibilityStatementUrl: 'https://bundled.example/accessibility',
};

function withLegal(legal: Partial<LegalLinks>) {
  const content = toPublicContent(installationBody);
  return { ...content, legal: { ...content.legal, ...legal } };
}

describe('resolveLegalLinks', () => {
  it('uses the bundled links while installation content is unavailable', () => {
    expect(resolveLegalLinks(undefined, bundled)).toEqual(bundled);
  });

  it("prefers Studio's links", () => {
    expect(resolveLegalLinks(toPublicContent(installationBody), bundled)).toEqual(
      installationBody.legal
    );
  });

  it('falls back per field for a missing imprint or privacy policy', () => {
    expect(resolveLegalLinks(withLegal({ imprintUrl: null }), bundled)).toEqual({
      ...installationBody.legal,
      imprintUrl: bundled.imprintUrl,
    });
    expect(resolveLegalLinks(withLegal({ privacyPolicyUrl: null }), bundled)).toEqual({
      ...installationBody.legal,
      privacyPolicyUrl: bundled.privacyPolicyUrl,
    });
  });

  it('falls back for a missing accessibility statement too, which Kassel must publish', () => {
    expect(
      resolveLegalLinks(withLegal({ accessibilityStatementUrl: null }), bundled)
        .accessibilityStatementUrl
    ).toBe(bundled.accessibilityStatementUrl);
  });

  it('omits a link that neither Studio nor the brand provides', () => {
    expect(
      resolveLegalLinks(withLegal({ accessibilityStatementUrl: null }), {
        ...bundled,
        accessibilityStatementUrl: null,
      }).accessibilityStatementUrl
    ).toBeNull();
  });
});
