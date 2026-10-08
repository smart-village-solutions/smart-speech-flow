import type { BrandId } from '@/app/config/env';
import type { LegalLinks } from '@/domain/content/content.types';

export interface BrandDefinition {
  id: BrandId;
  /** Shown while Studio's installation content is unavailable. */
  legal: LegalLinks;
}
