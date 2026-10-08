import { useBrand } from '@/app/providers/brand';
import type { LegalLinks } from '@/domain/content/content.types';
import { resolveLegalLinks } from './legalLinks';
import { usePublicContent } from './usePublicContent';

export function useLegalLinks(): LegalLinks {
  const { content } = usePublicContent();
  const { legal } = useBrand();
  return resolveLegalLinks(content, legal);
}
