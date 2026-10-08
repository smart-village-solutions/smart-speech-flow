import type { BrandId } from '@/app/config/env';
import type { BrandDefinition } from './brand.types';

/**
 * Accent colours live in src/ui/styles/brand.css and are selected by the
 * data-brand attribute, so this port carries identity and the bundled legal
 * links, which stand in while Studio's installation content is unavailable.
 * A GET /api/branding implementation replaces the static source later; it must
 * keep supplying those links (`NO_LEGAL_LINKS` for a brand without any).
 */
export interface BrandSource {
  list(): BrandDefinition[];
  getDefault(): BrandId;
}
