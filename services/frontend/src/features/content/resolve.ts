const primarySubtag = (locale: string) => locale.split('-')[0].toLowerCase();

/** Whether content written in `contentLocale` suits a screen shown in `screenLocale`. */
export function sameLanguage(contentLocale: string, screenLocale: string): boolean {
  return contentLocale !== '' && primarySubtag(contentLocale) === primarySubtag(screenLocale);
}

/** Content for a screen in `screenLocale`, or undefined so that every field falls back. */
export function inLocale<T extends { locale: string }>(
  content: T | null | undefined,
  screenLocale: string
): T | undefined {
  return content != null && sameLanguage(content.locale, screenLocale) ? content : undefined;
}

function isPresent(studio: string | null | undefined): studio is string {
  return studio != null && studio.trim() !== '';
}

/** Studio's text, or the bundled text when Studio has none. */
export function textOr(studio: string | null | undefined, bundled: string): string {
  return isPresent(studio) ? studio : bundled;
}

const ESCAPES: Readonly<Record<string, string>> = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };

/** A cleared rich-text field arrives as `<p></p>`; markup without text counts as missing. */
function hasText(html: string): boolean {
  return new DOMParser().parseFromString(html, 'text/html').body.textContent?.trim() !== '';
}

/** Studio's markup when it carries text; undefined means the caller's bundled copy. */
export function studioHtml(studio: string | null | undefined): string | undefined {
  return isPresent(studio) && hasText(studio) ? studio : undefined;
}

/** Studio's markup, or the bundled text as one paragraph, so the caller always renders RichText. */
export function htmlOr(studio: string | null | undefined, bundled: string): string {
  return (
    studioHtml(studio) ??
    `<p>${bundled.replaceAll(/[&<>]/g, (character) => ESCAPES[character])}</p>`
  );
}
