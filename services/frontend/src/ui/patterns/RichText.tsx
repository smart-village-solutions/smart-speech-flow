import { createElement, Fragment, isValidElement, useMemo, type ReactNode } from 'react';
import { isSafeHttpsUrl } from '@/core/http/url';

const LINK_CLASS =
  'text-fg-link underline underline-offset-2 transition-colors duration-200 hover:text-fg-link-hover';

const BLOCK_CLASS: Readonly<Record<string, string | undefined>> = {
  p: undefined,
  li: undefined,
  ul: 'list-inside list-disc',
  ol: 'list-inside list-decimal',
};
const FORMATTING = new Set(['strong', 'em']);
/** Removed with everything inside; any other unknown element is unwrapped to its text. */
const DROPPED = new Set([
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

function isMailto(href: string): boolean {
  try {
    return new URL(href).protocol === 'mailto:';
  } catch {
    return false;
  }
}

/** Credentials are refused: `https://dialog.kassel.de@evil.example/` reads as the city's site. */
function safeHref(element: Element): string | null {
  const href = element.getAttribute('href') ?? '';
  return isSafeHttpsUrl(href) || isMailto(href) ? new URL(href).href : null;
}

function isBlockTag(tag: string): boolean {
  return Object.hasOwn(BLOCK_CLASS, tag);
}

/** A line break alone is not content: `<p><br></p>` is an empty block. */
function isBlank(nodes: ReactNode[]): boolean {
  return nodes.every(
    (node) =>
      (typeof node === 'string' && node.trim() === '') ||
      (isValidElement(node) && node.type === 'br')
  );
}

function isBlock(node: ReactNode): boolean {
  return isValidElement(node) && typeof node.type === 'string' && isBlockTag(node.type);
}

function link(element: Element, children: ReactNode[]): ReactNode[] {
  const href = safeHref(element);
  if (href === null) {
    return children;
  }
  return [
    createElement(
      'a',
      { href, target: '_blank', rel: 'noopener noreferrer', className: LINK_CLASS },
      ...children
    ),
  ];
}

function block(tag: string, inline: boolean, children: ReactNode[]): ReactNode {
  return inline
    ? createElement('span', { className: 'block' }, ...children)
    : createElement(tag, { className: BLOCK_CLASS[tag] }, ...children);
}

/** An element outside the allowlist contributes its children to its parent. */
function wrap(element: Element, inline: boolean, children: ReactNode[]): ReactNode[] {
  const tag = element.localName;
  if (tag === 'a') return link(element, children);
  if (FORMATTING.has(tag)) return [createElement(tag, null, ...children)];
  if (isBlockTag(tag)) return [block(tag, inline, children)];
  return children;
}

function buildElement(element: Element, inline: boolean): ReactNode[] {
  if (DROPPED.has(element.localName)) return [];
  if (element.localName === 'br') return [createElement('br')];
  const children = buildChildren(element, inline);
  return isBlank(children) ? [] : wrap(element, inline, children);
}

function buildNode(node: Node, inline: boolean): ReactNode[] {
  if (node.nodeType === Node.TEXT_NODE) return [node.textContent ?? ''];
  if (node.nodeType !== Node.ELEMENT_NODE) return [];
  return buildElement(node as Element, inline);
}

function buildChildren(parent: Node, inline: boolean): ReactNode[] {
  return Array.from(parent.childNodes).flatMap((child) => buildNode(child, inline));
}

/**
 * The gateway unwraps `div`, `h2` and the like, leaving their text outside any
 * block. Each such run becomes a paragraph, so a caller's flex column does not
 * split one sentence into a flex item per text node.
 */
function paragraphs(nodes: ReactNode[]): ReactNode[] {
  const result: ReactNode[] = [];
  let run: ReactNode[] = [];
  const flush = () => {
    if (!isBlank(run)) result.push(createElement('p', null, ...run));
    run = [];
  };
  for (const node of nodes) {
    if (isBlock(node)) {
      flush();
      result.push(node);
    } else {
      run.push(node);
    }
  }
  flush();
  return result;
}

interface RichTextProps {
  /** Studio markup, sanitised by the gateway already; this is the browser's own allowlist. */
  html: string;
  /** Blocks become block-level spans, for use inside a label, heading or paragraph. */
  inline?: boolean;
}

/**
 * Renders Studio HTML by rebuilding allowlisted elements from parsed markup;
 * no HTML string is ever written into the page. Children go to createElement
 * as arguments, not as an array, so no element needs a key. The caller's
 * container sets the typography and the gap between paragraphs.
 */
export function RichText({ html, inline = false }: Readonly<RichTextProps>) {
  const nodes = useMemo(() => {
    const built = buildChildren(new DOMParser().parseFromString(html, 'text/html').body, inline);
    return inline ? built : paragraphs(built);
  }, [html, inline]);
  return createElement(Fragment, null, ...nodes);
}
