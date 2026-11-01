import { useTranslation } from 'react-i18next';

/** Ordinary entry always uses the controlled, localized introduction. */
export function ConsentProse() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-5 text-body font-normal leading-prose tracking-prose text-fg-body">
      <p>{t('consent.intro')}</p>
      <p>{t('consent.howTo')}</p>
    </div>
  );
}
