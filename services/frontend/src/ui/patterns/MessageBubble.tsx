import { Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useClipPeaks, usePlayback } from '@/app/providers/playback';
import { cn } from '@/lib/cn';
import { activeBarsForProgress } from '@/core/audio/waveform';
import type { ChatMessage } from '@/domain/message/message.types';
import { TypingDots } from './TypingDots';
import { Waveform } from './Waveform';

interface MessageBubbleProps {
  message: ChatMessage;
}

/**
 * Own bubbles sit left with a 46px right gutter and incoming bubbles sit right
 * with a 46px left gutter. That is the reverse of the usual chat convention and
 * is what the design specifies.
 *
 * Playback belongs to the conversation, not the bubble: incoming audio autoplays
 * on arrival and only one clip is ever audible, so the state lives in
 * `PlaybackProvider` and the control here always restarts from the beginning.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const { t } = useTranslation();
  const { playingId, progress, playNow } = usePlayback();

  const isOwn = message.origin === 'self';
  const isPending = message.state === 'pending';
  const isPlaying = playingId === message.id;
  const hasAudio = !isOwn && message.audioUrl !== null && !isPending;
  const peaks = useClipPeaks(hasAudio ? message.audioUrl : null);

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
        isOwn
          ? 'ms-bubble-inset me-bubble-gutter rounded-bubble-self'
          : 'ms-bubble-gutter me-bubble-inset self-end rounded-bubble-peer'
      )}
    >
      {isPending ? (
        <TypingDots />
      ) : (
        <p className={cn('text-body leading-chat text-fg-chat', hasAudio && 'mb-4')}>
          {message.text}
        </p>
      )}

      {hasAudio && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => playNow(message.id, message.audioUrl as string)}
            aria-label={isPlaying ? t('conversation.replay') : t('conversation.play')}
            className="flex size-9 shrink-0 items-center justify-center rounded-full border border-border-play text-fg-consent transition-colors duration-150"
          >
            <Play size={15} strokeWidth={2} />
          </button>

          <div className="flex-1">
            <Waveform
              activeBars={isPlaying ? activeBarsForProgress(progress) : 0}
              barColorClass="bg-accent"
              heights={peaks}
            />
          </div>
        </div>
      )}
    </div>
  );
}
