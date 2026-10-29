import { useTranslation } from 'react-i18next';
import type { ConsentRecord } from './records';

/** The served text is HTML; here it is only ever shown as text. */
function plainText(html: string): string {
  return new DOMParser().parseFromString(html, 'text/html').body.textContent ?? '';
}

export function ConsentBody({ record }: Readonly<{ record: ConsentRecord }>) {
  const { t } = useTranslation();
  const png = record.signature?.png;
  const text = record.text;
  return (
    <div className="flex flex-col gap-1 text-note text-fg-body">
      <p>
        {t(record.answer === 'yes' ? 'admin.archive.consent.yes' : 'admin.archive.consent.no')} ·{' '}
        {t(`admin.archive.consent.kind.${record.kind}`, { defaultValue: record.kind })}
      </p>
      {record.guest && (
        <p>
          {record.guest.name} {t(`admin.archive.consent.enteredBy.${record.guest.entered_by}`)}
        </p>
      )}
      {png && (
        <img
          src={`data:image/png;base64,${png}`}
          alt={t('admin.archive.consent.signature')}
          className="max-h-archive-signature self-start rounded-xl bg-signature-paper"
        />
      )}
      {record.id_check && (
        <p className="text-label text-fg-muted">
          {t(
            record.id_check.checked
              ? 'admin.archive.consent.idCheck'
              : 'admin.archive.consent.idNotChecked'
          )}
        </p>
      )}
      {text && (
        <>
          <p className="text-label text-fg-muted">
            {t('admin.archive.consent.citedText', {
              language: text.language,
              source: text.source,
              version: text.version,
              hash: text.sha256.slice(0, 12),
            })}
          </p>
          <details className="text-label text-fg-muted">
            <summary>{t('admin.archive.consent.text')}</summary>
            <p className="mt-1 whitespace-pre-wrap">{plainText(text.html)}</p>
          </details>
        </>
      )}
    </div>
  );
}
