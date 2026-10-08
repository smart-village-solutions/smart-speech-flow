import type { LegalLinks, PublicContent } from '@/domain/content/content.types';

/**
 * Studio's links over the brand's bundled ones. An imprint and a privacy policy
 * are required, so a missing one (the mapper nulls a non-https URL) falls back;
 * the accessibility statement is optional, and installation content without one
 * means the installation has none.
 */
export function resolveLegalLinks(
  content: PublicContent | undefined,
  bundled: LegalLinks
): LegalLinks {
  if (content === undefined) return bundled;
  const { imprintUrl, privacyPolicyUrl, accessibilityStatementUrl } = content.legal;
  return {
    imprintUrl: imprintUrl ?? bundled.imprintUrl,
    privacyPolicyUrl: privacyPolicyUrl ?? bundled.privacyPolicyUrl,
    accessibilityStatementUrl,
  };
}
