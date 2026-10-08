import type { LegalLinks, PublicContent } from '@/domain/content/content.types';

/**
 * Studio's links over the brand's bundled ones, field by field. A null Studio
 * URL may be missing or invalid (the mapper nulls a non-https one); either way
 * the bundled link stands in, so a bad Studio value cannot hide a statement
 * the operator must publish. A link neither provides is omitted.
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
    accessibilityStatementUrl: accessibilityStatementUrl ?? bundled.accessibilityStatementUrl,
  };
}
