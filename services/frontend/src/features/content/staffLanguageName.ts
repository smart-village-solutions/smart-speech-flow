import { textOr } from './resolve';

/** German is the one staff language. */
const STAFF_LANGUAGE = 'de';

/** The engine's German name; undefined for a code it rejects. */
function germanName(code: string): string | undefined {
  try {
    return new Intl.DisplayNames([STAFF_LANGUAGE], { type: 'language' }).of(code);
  } catch {
    return undefined;
  }
}

/** An engine without data for a language hands the code back, which is no name. */
function realName(name: string | undefined, code: string): string | undefined {
  return name?.toLowerCase() === code.toLowerCase() ? undefined : name;
}

interface StaffLanguageNameSources {
  /** Studio's `guestLanguageNames`. */
  studioNames: Readonly<Record<string, string>>;
  /** The bundled English name, when SSF lists the code. */
  english: string | undefined;
  /** The bundled label for a language nobody can name. */
  unknown: string;
  /** Replaceable because engines differ in which languages they can name. */
  displayName?: (code: string) => string | undefined;
}

/** A guest language as staff read it: Studio's name, the engine's German one, the bundled English one. */
export function staffLanguageName(
  code: string | null,
  { studioNames, english, unknown, displayName = germanName }: StaffLanguageNameSources
): string {
  if (code === null) return unknown;
  const studio = Object.hasOwn(studioNames, code) ? studioNames[code] : undefined;
  if (studio !== undefined && studio.trim() !== '') return studio;
  return textOr(realName(displayName(code), code), textOr(english, unknown));
}
