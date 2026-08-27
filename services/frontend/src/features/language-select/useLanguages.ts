import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { Language } from '@/domain/language/language.types';

/** The supported set changes only on deployment, so it never goes stale. */
export function useLanguages() {
  const { language } = useServices();

  return useQuery<Language[]>({
    queryKey: ['languages'],
    queryFn: () => language.listCustomerLanguages(),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
