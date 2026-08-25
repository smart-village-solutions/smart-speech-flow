export interface Language {
  code: string;
  /** The language's own name, e.g. العربية. The primary label in the picker. */
  native: string;
  /** The English name, e.g. Arabic. Shown as a subtitle when it differs. */
  english: string;
}
