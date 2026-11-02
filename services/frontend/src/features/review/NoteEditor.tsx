import { useTranslation } from 'react-i18next';
import {
  CATEGORIES,
  type Category,
  type Finding,
  MAX_FINDINGS,
  MAX_FINDING_TEXT,
} from '@/domain/review/findings';
import { Textarea } from '@/ui/primitives/Textarea';
import { type EditableFinding, editable } from './editable';

interface NoteEditorProps {
  findings: readonly EditableFinding[];
  onChange: (next: EditableFinding[]) => void;
}

const EMPTY: Finding = { category: 'translation_error', text: '', suggestion: '' };

/** One entry's findings in the concept §8.5 categories; the original is never edited. */
export function NoteEditor({ findings, onChange }: Readonly<NoteEditorProps>) {
  const { t } = useTranslation();
  const update = (index: number, change: Partial<Finding>) =>
    onChange(findings.map((finding, at) => (at === index ? { ...finding, ...change } : finding)));
  return (
    <div className="flex flex-col gap-2">
      {findings.map((finding, index) => (
        <fieldset
          key={finding.id}
          className="flex flex-col gap-2 rounded-xl border border-border-divider p-3"
        >
          <select
            aria-label={t('admin.review.category')}
            value={finding.category}
            onChange={(event) => update(index, { category: event.target.value as Category })}
            className="rounded-xl border border-border-card bg-surface-card px-3 py-2 text-note"
          >
            {CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {t(`admin.archive.verification.category.${category}`)}
              </option>
            ))}
          </select>
          <Textarea
            variant="field"
            aria-label={t('admin.review.findingText')}
            rows={3}
            maxLength={MAX_FINDING_TEXT}
            value={finding.text}
            onChange={(event) => update(index, { text: event.target.value })}
          />
          <Textarea
            variant="field"
            aria-label={t('admin.review.findingSuggestion')}
            rows={2}
            maxLength={MAX_FINDING_TEXT}
            value={finding.suggestion}
            onChange={(event) => update(index, { suggestion: event.target.value })}
          />
          <button
            type="button"
            onClick={() => onChange(findings.filter((_, at) => at !== index))}
            className="self-start text-label font-medium text-fg-danger"
          >
            {t('admin.review.removeFinding')}
          </button>
        </fieldset>
      ))}
      {findings.length < MAX_FINDINGS && (
        <button
          type="button"
          onClick={() => onChange([...findings, editable(EMPTY)])}
          className="self-start text-label font-medium text-fg-link"
        >
          {t('admin.review.addFinding')}
        </button>
      )}
    </div>
  );
}
