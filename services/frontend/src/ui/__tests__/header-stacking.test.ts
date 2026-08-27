import { describe, expect, it } from 'vitest';

/**
 * `AppHeader` is `fixed` with a z-index, which makes it a stacking context. The
 * admin user menu hangs out of the bottom of it, and its own `z-50` is sealed
 * inside that context — it cannot lift the menu over anything outside the
 * header. What decides that is the header's z-index alone.
 *
 * Both status overlays sit at `z-10` and are rendered *after* the header, so at
 * an equal z-index they won on document order and painted straight over the
 * open menu. jsdom has no stacking model and no layout, so nothing in the test
 * suite would notice; this compares the source instead.
 */
const sources = import.meta.glob('/src/{features,ui}/**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function read(path: string): string {
  const source = sources[path];
  if (source === undefined) {
    throw new Error(`${path} is not there any more; this guard needs repointing`);
  }
  return source;
}

/** The z-index on the element opening `tag`, read from its class list. */
function layerOf(path: string, tag: string): number {
  const opening = new RegExp(`<${tag}\\b[^>]*className="([^"]*)"`).exec(read(path));
  if (opening === null) {
    throw new Error(`no <${tag}> with a literal className in ${path}`);
  }

  const layer = /\bz-(\d+)\b/.exec(opening[1]);
  if (layer === null) {
    throw new Error(`<${tag}> in ${path} carries no z-index; it needs one to stack`);
  }
  return Number(layer[1]);
}

const HEADER = '/src/ui/patterns/AppHeader.tsx';

const OVERLAYS = [
  ['/src/features/admin/SessionStatusOverlay.tsx', 'div'],
  ['/src/features/conversation/ConversationStatus.tsx', 'div'],
] as const;

describe('header stacking', () => {
  it.each(OVERLAYS)('keeps the header above %s', (path, tag) => {
    expect(layerOf(HEADER, 'header')).toBeGreaterThan(layerOf(path, tag));
  });

  // A dialog covers the whole screen and must cover the header with it.
  it.each([
    ['/src/ui/patterns/ConfirmDialog.tsx'],
    ['/src/features/admin/AdminInviteOverlay.tsx'],
    ['/src/features/feedback/FeedbackSheet.tsx'],
  ])('keeps %s above the header', (path) => {
    const layers = [...read(path).matchAll(/\bz-(\d+)\b/g)].map((match) => Number(match[1]));
    expect(layers.length).toBeGreaterThan(0);
    expect(Math.min(...layers)).toBeGreaterThan(layerOf(HEADER, 'header'));
  });
});
