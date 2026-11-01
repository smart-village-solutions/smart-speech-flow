/** Removed with everything inside; any other unknown element is unwrapped to its text. */
export const DROPPED_RICH_TEXT_ELEMENTS = new Set([
  'script',
  'style',
  'iframe',
  'svg',
  'math',
  'template',
  'noscript',
  'object',
  'embed',
  'textarea',
  'select',
]);

function hasVisibleText(node: Node): boolean {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').trim().length > 0;
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  if (DROPPED_RICH_TEXT_ELEMENTS.has((node as Element).localName)) return false;
  return Array.from(node.childNodes).some(hasVisibleText);
}

/** Uses RichText's drop policy: markup, blank entities and discarded children are not wording. */
export function hasVisibleRichText(html: string): boolean {
  return hasVisibleText(new DOMParser().parseFromString(html, 'text/html').body);
}
