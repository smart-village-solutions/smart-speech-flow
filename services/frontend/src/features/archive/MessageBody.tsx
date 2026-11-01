import { useTranslation } from 'react-i18next';
import { listedObjects } from '@/core/crypto/chain';
import type { ArchivedEntry, OpenedConversation } from '@/domain/archive/archive.types';
import { AudioButton } from './AudioButton';
import type { MessageRecord } from './records';

interface MessageBodyProps {
  record: MessageRecord;
  entry: ArchivedEntry;
  opened: OpenedConversation;
  keys: ReadonlyMap<string, CryptoKey>;
}

function Row({ label, text }: Readonly<{ label: string; text: string | null | undefined }>) {
  if (text === null || text === undefined || text === '') return null;
  return (
    <div className="flex flex-col">
      <span className="text-meta font-medium text-fg-muted">{label}</span>
      <span className="text-note text-fg-body">{text}</span>
    </div>
  );
}

/** The refined text, only where refinement ran and its output was used (spec §7). */
function refinement(record: MessageRecord): { text: string; changed: boolean } | null {
  const step = record.steps.find((item) => item.name === 'refinement');
  if (step?.status !== 'success' || typeof step.output !== 'string') return null;
  return { text: step.output, changed: step.changed === true };
}

export function MessageBody({ record, entry, opened, keys }: Readonly<MessageBodyProps>) {
  const { t } = useTranslation();
  const refined = refinement(record);
  const types = new Set(listedObjects(entry).map((item) => item.type));
  const refinedLabel = refined?.changed
    ? `${t('admin.archive.message.refined')} ${t('admin.archive.message.changed')}`
    : t('admin.archive.message.refined');

  return (
    <>
      <Row label={t('admin.archive.message.asr')} text={record.source_text} />
      <Row label={t('admin.archive.message.rawMt')} text={record.raw_translation} />
      <Row label={refinedLabel} text={refined?.text} />
      <Row label={t('admin.archive.message.final')} text={record.final_text} />
      {record.error && (
        <p className="text-label text-fg-status-alert">
          {t('admin.archive.failed', {
            stage: record.error.stage ?? '–',
            code: record.error.code ?? '–',
          })}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {types.has('original.wav') && (
          <AudioButton
            opened={opened}
            keys={keys}
            entryId={entry.entryId}
            objectType="original.wav"
          />
        )}
        {types.has('translated.wav') && (
          <AudioButton
            opened={opened}
            keys={keys}
            entryId={entry.entryId}
            objectType="translated.wav"
          />
        )}
      </div>
    </>
  );
}
