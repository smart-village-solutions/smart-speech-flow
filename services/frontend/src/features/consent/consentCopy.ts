import type { GuestContent } from '@/domain/content/content.types';
import { studioHtml } from '@/features/content/resolve';

/** What the consent screen shows; an undefined text means the bundled copy. */
export interface ConsentCopy {
  explanationHtml: string | undefined;
}

export function consentCopy(content: GuestContent | undefined): ConsentCopy {
  if (content?.provided !== true) {
    return { explanationHtml: undefined };
  }
  return { explanationHtml: studioHtml(content.explanationHtml) };
}
