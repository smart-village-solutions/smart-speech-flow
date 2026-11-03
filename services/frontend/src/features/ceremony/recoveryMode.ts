import type { TFunction } from 'i18next';

/** The concept's two modes (§7.7): one approval is standard, more is enhanced. */
export function recoveryModeText(t: TFunction, k: number): string {
  return k === 1 ? t('admin.ceremony.modeStandard') : t('admin.ceremony.modeEnhanced', { k });
}
