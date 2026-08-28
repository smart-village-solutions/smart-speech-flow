import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import type { ChatMessage } from '@/domain/message/message.types';
import { BubblePlayer } from './BubblePlayer';
import { TypingDots } from './TypingDots';

interface MessageBubbleProps {
  message: ChatMessage;
}

/**
 * Own bubbles sit left with a 46px right gutter and incoming bubbles sit right
 * with a 46px left gutter. That is the reverse of the usual chat convention and
 * is what the design specifies.
 *
 * The player itself is `BubblePlayer`, which owns everything to do with
 * playback; the bubble only needs to know whether there is any, to give itself a
 * width and to space the text above it.
 */
export function MessageBubble({ message }: Readonly<MessageBubbleProps>) {
  const { t } = useTranslation();

  const isOwn = message.origin === 'self';
  const isPending = message.state === 'pending';
  const isFailed = message.state === 'failed';
  const hasAudio = !isOwn && message.audioUrl !== null && !isPending;

  return (
    <div
      // Marks the landing spot for a send flight; see useSendFlight. A send
      // that confirms before the flight measures leaves no pending bubble, so
      // every bubble is a candidate and the last one stands in.
      data-bubble=""
      data-pending={isPending ? '' : undefined}
      // The margin classes are branch-exclusive on purpose: tailwind-merge does
      // not recognise custom named spacing, so emitting both sides would leave
      // stylesheet order to decide the gutter.
      className={cn(
        'max-w-bubble border border-border-card bg-surface-card p-4',
        // A typing bubble hugs the dots instead of stretching to the stack width.
        isPending && 'w-fit',
        isFailed && 'border-border-status-alert',
        isOwn
          ? 'ms-bubble-inset me-bubble-gutter rounded-bubble-self'
          : 'ms-bubble-gutter me-bubble-inset self-end rounded-bubble-peer',
        // `self-end` sizes a bubble to its content, and the waveform's bars are
        // all `flex-1` — they contribute nothing to that measurement, so the row
        // collapsed to its 49 gaps and every bar came out zero pixels wide. A
        // definite width settles the row before the bars divide it, which is
        // also what makes bar width the same in every bubble instead of a
        // function of how long the message happened to be.
        hasAudio && 'w-bubble-span'
      )}
    >
      {isPending ? (
        <TypingDots />
      ) : (
        <p className={cn('text-body leading-chat text-fg-chat', hasAudio && 'mb-4')}>
          {message.text}
        </p>
      )}

      {/* A failed send stops being pending, so without this the bubble showed
          the placeholder's empty text: a blank card with nothing to act on. */}
      {isFailed && (
        <p data-testid="failed-message" className="text-meta text-fg-status-alert">
          {t('conversation.notSent')}
        </p>
      )}

      {hasAudio && <BubblePlayer messageId={message.id} audioUrl={message.audioUrl as string} />}
    </div>
  );
}
