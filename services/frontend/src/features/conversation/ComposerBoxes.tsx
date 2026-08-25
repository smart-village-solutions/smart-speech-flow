import type { RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { RECORDING_SECONDS } from '@/core/audio/waveform';
import { cn } from '@/lib/cn';
import { RecordingBubble } from '@/ui/patterns/RecordingBubble';
import { TypingDots } from '@/ui/patterns/TypingDots';
import { Textarea } from '@/ui/primitives/Textarea';
import type { SendFlight } from './useSendFlight';

interface ComposerBoxesProps {
  bottom: string;
  flight: SendFlight | null;
  sourceRef: RefObject<HTMLDivElement | null>;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  recording: boolean;
  levels: number[];
  elapsedSeconds: number;
  typing: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

/** Offsets above the buttons row, per SCREEN_SPECS (export 935-936, 953-954). */
const OFFSET = { recording: '120px', typing: '96px' } as const;

/**
 * The two boxes above the mic and keyboard buttons, and the dots box that
 * replaces either one on send and flies to the chat stack.
 */
export function ComposerBoxes({
  bottom,
  flight,
  sourceRef,
  composerRef,
  recording,
  levels,
  elapsedSeconds,
  typing,
  draft,
  onDraftChange,
  onSubmit,
  onCancel,
}: ComposerBoxesProps) {
  const { t } = useTranslation();

  if (flight !== null) {
    const { from, to } = flight;

    return (
      <Slot bottom={bottom} offset={OFFSET[flight.kind]}>
        <div
          className={cn(
            'send-flight ms-bubble-inset me-bubble-gutter rounded-bubble-self border border-border-card bg-surface-card p-4',
            // The lift goes as it lands, so it settles flush with the bubble.
            to === null && 'shadow-xl'
          )}
          style={{
            width: to?.width ?? from.width,
            height: to?.height ?? from.height,
            transform: to?.transform,
            opacity: to === null ? 1 : 0,
          }}
        >
          <TypingDots />
        </div>
      </Slot>
    );
  }

  if (recording) {
    return (
      <Slot bottom={bottom} offset={OFFSET.recording}>
        <RecordingBubble
          ref={sourceRef}
          totalSeconds={RECORDING_SECONDS}
          levels={levels}
          elapsedSeconds={elapsedSeconds}
        />
      </Slot>
    );
  }

  if (!typing) {
    return null;
  }

  return (
    <Slot bottom={bottom} offset={OFFSET.typing}>
      <div
        ref={sourceRef}
        data-composer-keep=""
        className="mx-bubble-inset max-w-bubble rounded-bubble-self border border-border-card bg-surface-card shadow-xl"
      >
        <Textarea
          ref={composerRef}
          rows={3}
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
            if (event.key === 'Escape') {
              onCancel();
            }
          }}
          placeholder={t('conversation.placeholder')}
          className="px-4 pb-2 pt-4"
        />
      </div>
    </Slot>
  );
}

function Slot({
  bottom,
  offset,
  children,
}: {
  bottom: string;
  offset: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn('absolute inset-x-0 transition-[bottom] duration-300')}
      style={{ bottom: `calc(${bottom} + ${offset})` }}
    >
      {children}
    </div>
  );
}
