import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useFavicon } from '@/ui/hooks/useFavicon';

const STUDIO_ICON = 'https://dialog.kassel.de/favicon-200x200.png';

function addLink(rel: string, href: string, type?: string): HTMLLinkElement {
  const link = document.createElement('link');
  link.rel = rel;
  link.setAttribute('href', href);
  if (type !== undefined) link.type = type;
  document.head.append(link);
  return link;
}

let png: HTMLLinkElement;
let ico: HTMLLinkElement;
let shortcut: HTMLLinkElement;
let apple: HTMLLinkElement;

beforeEach(() => {
  png = addLink('icon', '/favicon-32x32.png', 'image/png');
  ico = addLink('icon', '/favicon.ico', 'image/vnd.microsoft.icon');
  shortcut = addLink('shortcut icon', '/favicon.ico', 'image/vnd.microsoft.icon');
  apple = addLink('apple-touch-icon', '/apple-touch-icon.png');
});

afterEach(() => {
  document.head.replaceChildren();
});

describe('useFavicon', () => {
  it('points every icon link at the given icon and drops their static types', () => {
    renderHook(() => useFavicon(STUDIO_ICON));

    for (const link of [png, ico, shortcut]) {
      expect(link.getAttribute('href')).toBe(STUDIO_ICON);
      expect(link.hasAttribute('type')).toBe(false);
    }
    expect(apple.getAttribute('href')).toBe('/apple-touch-icon.png');
  });

  it('leaves the static set alone without an icon', () => {
    renderHook(() => useFavicon(null));

    expect(png.getAttribute('href')).toBe('/favicon-32x32.png');
    expect(ico.getAttribute('type')).toBe('image/vnd.microsoft.icon');
  });

  it('restores the static set when the icon goes away or the hook unmounts', () => {
    const { rerender, unmount } = renderHook(({ href }) => useFavicon(href), {
      initialProps: { href: STUDIO_ICON as string | null },
    });

    rerender({ href: null });
    expect(png.getAttribute('href')).toBe('/favicon-32x32.png');
    expect(png.getAttribute('type')).toBe('image/png');

    rerender({ href: STUDIO_ICON });
    unmount();
    expect(ico.getAttribute('href')).toBe('/favicon.ico');
    expect(shortcut.getAttribute('type')).toBe('image/vnd.microsoft.icon');
  });
});
