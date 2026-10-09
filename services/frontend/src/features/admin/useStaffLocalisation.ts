import { useTranslation } from 'react-i18next';
import type { Language } from '@/domain/language/language.types';
import { staffLanguageName } from '@/features/content/staffLanguageName';
import { useStaffContent } from '@/features/content/useStaffContent';
// The languages query is a hook over a domain repository, not UI. Duplicating
// it in this feature would be worse than importing it across the boundary.
import { useLanguages } from '@/features/language-select/useLanguages';

/** A guest language as staff see it. */
export interface StaffLanguage {
  /** SSF's own entry, for the flag; null for a code SSF does not list. */
  bundled: Language | null;
  /** The name in German. */
  name: string;
}

/**
 * Guest languages named in German and the tenant's time zone (null: the
 * browser's). Neither needs Studio: both fall back when staff content fails.
 */
export function useStaffLocalisation() {
  const { t } = useTranslation();
  const { data: languages = [] } = useLanguages();
  const { content } = useStaffContent();
  const studioNames = content?.guestLanguageNames ?? {};
  const unknown = t('admin.sessions.unknownLanguage');

  const languageOf = (code: string | null): StaffLanguage => {
    const bundled = languages.find((language) => language.code === code) ?? null;
    return {
      bundled,
      name: staffLanguageName(code, { studioNames, english: bundled?.english, unknown }),
    };
  };

  return { languageOf, timeZone: content?.timeZone ?? null };
}
