import { usePublicContent } from '@/features/content/usePublicContent';

/**
 * Renders once installation content has arrived or failed. Beside a screen it
 * shares that screen's query, so finding it means the screen has already
 * re-rendered with whatever content there is.
 */
export function ContentSettled() {
  return usePublicContent().settled ? <span data-testid="public-content-settled" hidden /> : null;
}
