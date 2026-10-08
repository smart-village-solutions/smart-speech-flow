import type { LegalLinks } from '@/domain/content/content.types';

/** A brand without bundled legal pages: until Studio sends some, no links are shown. */
export const NO_LEGAL_LINKS: LegalLinks = {
  imprintUrl: null,
  privacyPolicyUrl: null,
  accessibilityStatementUrl: null,
};
