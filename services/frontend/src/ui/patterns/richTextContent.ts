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
