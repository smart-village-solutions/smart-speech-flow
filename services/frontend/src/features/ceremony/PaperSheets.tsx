import { useTranslation } from 'react-i18next';
import { scalarToBytes, toHex } from '@/core/crypto/bytes';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import type { PaperSheet } from './usePaperDevice';

interface PaperSheetsProps {
  ceremony: Ceremony;
  tenantId: string;
  sheets: PaperSheet[];
}

function grouped(share: bigint): string {
  return (toHex(scalarToBytes(share)).match(/.{4}/g) ?? []).join(' ');
}

/** One printed page per paper share, each sealed separately and held by a different person. */
export function PaperSheets({ ceremony, tenantId, sheets }: Readonly<PaperSheetsProps>) {
  const { t } = useTranslation();
  const n = ceremony.participants.length;

  return (
    <div className="hidden print:block">
      {sheets.map((sheet) => (
        <article key={sheet.holderIndex} className="flex break-after-page flex-col gap-4 p-8 text-fg-strong">
          <h1 className="text-thanks font-semibold">{t('admin.ceremony.sheetTitle')}</h1>
          <p>{t('admin.ceremony.sheetWarning', { k: ceremony.k })}</p>
          <dl className="grid grid-cols-2 gap-2">
            <dt>{t('admin.ceremony.sheetTenant')}</dt>
            <dd>{tenantId}</dd>
            <dt>{t('admin.ceremony.sheetKey')}</dt>
            <dd>{ceremony.recoveryKeyId ?? ceremony.ceremonyId}</dd>
            {ceremony.kind === 'resharing' && (
              // Old and new sheets of the same key can be told apart (spec §9.7).
              <>
                <dt>{t('admin.ceremony.reshare.sheetCeremony')}</dt>
                <dd>{ceremony.ceremonyId}</dd>
              </>
            )}
            <dt>{t('admin.ceremony.sheetHolder')}</dt>
            <dd>{t('admin.ceremony.sheetHolderValue', { ref: sheet.holderRef, index: sheet.holderIndex, n })}</dd>
          </dl>
          <code className="text-body font-semibold">{grouped(sheet.share)}</code>
        </article>
      ))}
    </div>
  );
}
