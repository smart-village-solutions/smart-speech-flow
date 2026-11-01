import type { LegalInformation } from '@/domain/content/content.types';
import { RichText } from '@/ui/patterns/RichText';

/** Shared sanitized source wording, without consent or recording controls. */
export function LegalInformationSections({
  information,
}: Readonly<{ information: LegalInformation }>) {
  return information.sections.map((section) => (
    <section key={section.id}>
      <h2 className="mb-2 font-semibold text-fg-strong">{section.headline}</h2>
      <div className="space-y-3">
        <RichText html={section.bodyHtml} />
      </div>
    </section>
  ));
}
