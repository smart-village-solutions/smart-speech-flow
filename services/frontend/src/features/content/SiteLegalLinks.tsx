import type { LegalInformation } from '@/domain/content/content.types';
import { LegalInformationDialog } from './LegalInformationDialog';
import { LegalLinks, type LegalLinksTone } from '@/ui/patterns/LegalLinks';
import { useLegalLinks } from './useLegalLinks';

interface SiteLegalLinksProps {
  information?: LegalInformation | null;
  tone?: LegalLinksTone;
  className?: string;
}

/** The installation's legal links, so a screen places them without wiring their source. */
export function SiteLegalLinks({ tone, className, information }: Readonly<SiteLegalLinksProps>) {
  const links = useLegalLinks();
  if (information == null) {
    return <LegalLinks links={links} tone={tone} className={className} />;
  }
  return (
    <div className={className}>
      <LegalLinks links={links} tone={tone} />
      <div className="mt-1 text-center">
        <LegalInformationDialog information={information} tone={tone} />
      </div>
    </div>
  );
}
