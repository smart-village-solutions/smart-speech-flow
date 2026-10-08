import { useEffect } from 'react';

function restore(link: HTMLLinkElement, name: string, value: string | null): void {
  if (value === null) link.removeAttribute(name);
  else link.setAttribute(name, value);
}

/** Points the page's icon links at `href`; null, or unmounting, restores index.html's set. */
export function useFavicon(href: string | null): void {
  useEffect(() => {
    if (href === null) return;

    const saved = [...document.head.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')].map(
      (link) => ({ link, href: link.getAttribute('href'), type: link.getAttribute('type') })
    );
    for (const { link } of saved) {
      link.setAttribute('href', href);
      // The static set declares PNG and ICO types, which need not match this icon.
      link.removeAttribute('type');
    }

    return () => {
      for (const entry of saved) {
        restore(entry.link, 'href', entry.href);
        restore(entry.link, 'type', entry.type);
      }
    };
  }, [href]);
}
