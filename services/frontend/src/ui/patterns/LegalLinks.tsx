import { useTranslation } from 'react-i18next';
import type { LegalLinks as LegalLinkUrls } from '@/domain/content/content.types';
import { cn } from '@/lib/cn';

/** `light` is for surfaces that stay white in both themes: the footer bar and the not-found page. */
export type LegalLinksTone = 'themed' | 'light';

interface LegalLinksProps {
  links: LegalLinkUrls;
  tone?: LegalLinksTone;
  className?: string;
}

const ENTRIES = [
  { field: 'imprintUrl', label: 'legal.imprint' },
  { field: 'privacyPolicyUrl', label: 'legal.privacyPolicy' },
  { field: 'accessibilityStatementUrl', label: 'legal.accessibilityStatement' },
] as const;

const TONE: Record<LegalLinksTone, string> = {
  themed: 'text-fg-consent hover:text-fg-consent-hover',
  light: 'text-black/60 hover:text-black',
};

/** Imprint, privacy policy and accessibility statement; a link without a URL is left out. */
export function LegalLinks({ links, tone = 'themed', className }: Readonly<LegalLinksProps>) {
  const { t } = useTranslation();
  const present = ENTRIES.flatMap(({ field, label }) => {
    const url = links[field];
    return url === null ? [] : [{ label, url }];
  });

  if (present.length === 0) return null;

  return (
    <nav aria-label={t('legal.label')} className={className}>
      <ul className="flex flex-wrap justify-center gap-x-5 gap-y-1">
        {present.map(({ label, url }) => (
          <li key={label}>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                'text-label leading-snug tracking-link underline underline-offset-2 transition-colors duration-200',
                TONE[tone]
              )}
            >
              {t(label)} <span className="sr-only">{t('legal.opensInNewTab')}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
