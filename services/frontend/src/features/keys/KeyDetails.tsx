import { ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function KeyDetails({ fingerprint }: Readonly<{ fingerprint: string }>) {
  const { t } = useTranslation();
  return (
    <details className="group border-t border-border-divider pt-2">
      <summary className="focus-ring flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg text-label font-medium text-fg-strong [&::-webkit-details-marker]:hidden">
        <ChevronDown aria-hidden className="size-4 -rotate-90 group-open:rotate-0" />
        {t('admin.keys.detailsAction')}
      </summary>
      <p className="text-note leading-chat text-fg-muted">{t('admin.keys.fingerprintHint')}</p>
      <code className="mt-1 block break-words text-body font-semibold text-fg-strong">
        {fingerprint}
      </code>
    </details>
  );
}
