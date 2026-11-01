import { useTranslation } from 'react-i18next';
import type { LegalInformation } from '@/domain/content/content.types';
import { RichText } from '@/ui/patterns/RichText';
import { hasVisibleRichText } from '@/ui/patterns/richTextContent';
import { directionFor } from '@/i18n';

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

/** The ordinary entry explains documentation recording; release remains separate. */
export function DocumentationInformation({
  information,
}: Readonly<{ information?: LegalInformation | null }>) {
  const { t } = useTranslation();
  if (!information) return null;
  const sections = information.sections.filter(
    ({ id }) => id === 'mode2Consent' || id === 'guestRecordingRelease'
  );
  if (
    !['mode2Consent', 'guestRecordingRelease'].every((id) =>
      sections.some(
        (section) =>
          section.id === id &&
          section.headline.trim().length > 0 &&
          hasVisibleRichText(section.bodyHtml)
      )
    )
  )
    return null;
  return (
    <section
      role="region"
      aria-label={t('legal.informationTitle')}
      className="mt-8 space-y-5 text-note leading-chat text-fg-body"
    >
      <p>{t('legal.informationNotice')}</p>
      <p className="text-label text-fg-muted">
        {t('legal.informationSource', {
          locale: information.locale,
          version: information.version,
        })}
      </p>
      <div lang={information.locale} dir={directionFor(information.locale)} className="space-y-5">
        <LegalInformationSections information={{ ...information, sections }} />
      </div>
    </section>
  );
}
