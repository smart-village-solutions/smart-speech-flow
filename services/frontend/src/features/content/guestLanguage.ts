import type { GuestLanguage } from '@/domain/content/content.types';
import type { Language } from '@/domain/language/language.types';
import { textOr } from './resolve';

/** A guest language as the picker and consent screen show it. */
export interface LanguageChoice extends Language {
  /** Studio's icon; null means the bundled flag. */
  iconUrl: string | null;
}

/** Studio's native name and icon where Studio provides the language; the English name stays bundled. */
export function languageChoice(language: GuestLanguage): LanguageChoice {
  const names = { code: language.code, english: language.name };
  if (!language.provided) return { ...names, native: language.native, iconUrl: null };
  return {
    ...names,
    native: textOr(language.nativeName, language.native),
    iconUrl: language.icon?.url ?? null,
  };
}
