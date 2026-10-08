import type { GuestContent } from '@/domain/content/content.types';
import { studioHtml } from '@/features/content/resolve';

/** What the consent screen shows; an undefined text means the bundled copy. */
export interface ConsentCopy {
  explanationHtml: string | undefined;
  /** Only a live `ask` offers storage; without content the mode is unknown. */
  asksStorage: boolean;
  questionHtml: string | undefined;
}

export function consentCopy(content: GuestContent | undefined): ConsentCopy {
  const asksStorage = content?.storage.mode === 'ask';
  if (content?.provided !== true) {
    return { explanationHtml: undefined, asksStorage, questionHtml: undefined };
  }
  return {
    explanationHtml: studioHtml(content.explanationHtml),
    asksStorage,
    questionHtml: studioHtml(content.storageQuestionHtml),
  };
}
