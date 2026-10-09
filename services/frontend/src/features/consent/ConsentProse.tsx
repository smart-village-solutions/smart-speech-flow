import { useTranslation } from 'react-i18next';
import { RichText } from '@/ui/patterns/RichText';

interface ConsentProseProps {
  /** Studio's explanation; undefined means the bundled paragraphs. */
  explanationHtml: string | undefined;
  /** The bundled opt-in paragraph offers storage, so it shows only when storage is asked. */
  showsOptIn: boolean;
}

/** Studio's explanation is one block and renders as delivered, its opt-in paragraph included. */
export function ConsentProse({ explanationHtml, showsOptIn }: Readonly<ConsentProseProps>) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-5 text-body font-normal leading-prose tracking-prose text-fg-body">
      {explanationHtml === undefined ? (
        <>
          <p>{t('consent.intro')}</p>
          <p>{t('consent.howTo')}</p>
          <p>{t('consent.retention')}</p>
          {showsOptIn && <p className="opacity-65">{t('consent.optIn')}</p>}
        </>
      ) : (
        <RichText html={explanationHtml} />
      )}
    </div>
  );
}
