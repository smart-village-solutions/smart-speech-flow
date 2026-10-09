import type { FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { RichText } from '@/ui/patterns/RichText';

/** A block container, so Studio's paragraphs never land inside a `<p>`. */
export function FeedbackNotice({ notice }: Readonly<{ notice: FeedbackFormDefinition['notice'] }>) {
  return (
    <div className="flex flex-col gap-1 text-caption leading-chat text-fg-subtle">
      {notice.kind === 'html' ? (
        <RichText html={notice.html} />
      ) : (
        notice.lines.map((line) => <p key={line.id}>{line.text}</p>)
      )}
    </div>
  );
}
