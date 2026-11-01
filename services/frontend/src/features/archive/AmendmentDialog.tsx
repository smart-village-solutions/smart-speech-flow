import { Textarea } from '@/ui/primitives/Textarea';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { formatTime } from './format';
import { AMENDMENT_MAX, type Amend } from './useAmend';

interface AmendmentDialogProps {
  opened: OpenedConversation;
  amend: Amend;
  references: readonly string[];
  onClose: () => void;
}

/** An amendment references entries and changes none of them (spec §10.4, concept §12.4). */
export function AmendmentDialog({
  opened,
  amend,
  references,
  onClose,
}: Readonly<AmendmentDialogProps>) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const [text, setText] = useState('');
  const trimmed = text.trim();
  const named = references
    .map((ref) => opened.entries.find((entry) => entry.entryId === ref))
    .filter((entry) => entry !== undefined)
    .map((entry) =>
      [formatTime(entry.createdAt, i18n.language), t(`admin.archive.kind.${entry.kind}`)].join(' ')
    )
    .join(', ');

  return (
    <QuestionDialog
      open
      title={t('admin.archive.amendment.title')}
      confirmLabel={t(
        amend.unconfirmed ? 'admin.archive.amendment.retry' : 'admin.archive.amendment.submit'
      )}
      cancelLabel={t('admin.archive.amendment.cancel')}
      error={amend.failure === null ? null : t(`admin.archive.amendment.error.${amend.failure}`)}
      confirmDisabled={
        amend.pending || (!amend.unconfirmed && (trimmed === '' || trimmed.length > AMENDMENT_MAX))
      }
      onConfirm={() => void (amend.unconfirmed ? amend.retry() : amend.submit(references, trimmed))}
      onCancel={onClose}
    >
      <p className="mt-2 text-label text-fg-muted">
        {t('admin.archive.amendment.references', { entries: named })}
      </p>
      <div className="mt-4 flex flex-col gap-1.5">
        <label htmlFor={id} className="text-label font-medium text-fg-body">
          {t('admin.archive.amendment.text')}
        </label>
        <Textarea variant="field"
          id={id}
          value={text}
          maxLength={AMENDMENT_MAX}
          readOnly={amend.unconfirmed}
          onChange={(event) => setText(event.target.value)}
          className="min-h-archive-signature"
        />
        <span className="self-end text-meta text-fg-muted">
          {t('admin.archive.amendment.count', { count: text.length })}
        </span>
      </div>
    </QuestionDialog>
  );
}
