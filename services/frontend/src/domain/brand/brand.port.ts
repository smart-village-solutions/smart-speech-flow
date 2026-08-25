import type { BrandId } from '@/app/config/env';
import type { BrandDefinition } from './brand.types';

/**
 * Accent colours live in src/ui/styles/brand.css and are selected by the
 * data-brand attribute, so this port carries identity only. A GET /api/branding
 * implementation replaces the static source later.
 */
export interface BrandSource {
  list(): BrandDefinition[];
  getDefault(): BrandId;
}
