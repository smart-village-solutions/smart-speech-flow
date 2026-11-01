import { useTranslation } from 'react-i18next';

interface ConsentProseProps {
  /** The bundled opt-in paragraph offers storage, so it shows only when storage is asked. */
  showsOptIn: boolean;
}

/** Keep the controlled introduction independent of optional Studio explanations. */
export function ConsentProse({ showsOptIn }: Readonly<ConsentProseProps>) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-5 text-body font-normal leading-prose tracking-prose text-fg-body">
      <p>{t('consent.intro')}</p>
      <p>{t('consent.howTo')}</p>
      {showsOptIn && <p className="opacity-65">{t('consent.optIn')}</p>}
    </div>
  );
}
