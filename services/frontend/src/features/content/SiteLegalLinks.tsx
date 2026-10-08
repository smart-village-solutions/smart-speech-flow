import { LegalLinks, type LegalLinksTone } from '@/ui/patterns/LegalLinks';
import { useLegalLinks } from './useLegalLinks';

interface SiteLegalLinksProps {
  tone?: LegalLinksTone;
  className?: string;
}

/** The installation's legal links, so a screen places them without wiring their source. */
export function SiteLegalLinks({ tone, className }: Readonly<SiteLegalLinksProps>) {
  return <LegalLinks links={useLegalLinks()} tone={tone} className={className} />;
}
