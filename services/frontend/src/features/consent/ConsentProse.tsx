import { useTranslation } from 'react-i18next';
import { RichText } from '@/ui/patterns/RichText';

interface ConsentProseProps {
  /** Studio's explanation; undefined means the bundled paragraphs. */
  explanationHtml: string | undefined;
}

/** Studio's explanation is one block and renders as delivered. */
export function ConsentProse({ explanationHtml }: Readonly<ConsentProseProps>) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-5 text-body font-normal leading-prose tracking-prose text-fg-body">
      {explanationHtml === undefined ? (
        <>
          <p>{t('consent.intro')}</p>
          <p>{t('consent.howTo')}</p>
          <p>{t('consent.retention')}</p>
        </>
      ) : (
        <RichText html={explanationHtml} />
      )}
    </div>
  );
}
