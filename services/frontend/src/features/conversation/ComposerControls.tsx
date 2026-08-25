import { Keyboard, Mic, SendHorizontal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';

interface ComposerControlsProps {
  bottom: string;
  recording: boolean;
  typing: boolean;
  canCompose: boolean;
  hasDraft: boolean;
  onMic: () => void;
  onKeyboard: () => void;
}

/** The mic and keyboard buttons; each doubles as the send control for its mode. */
export function ComposerControls({
  bottom,
  recording,
  typing,
  canCompose,
  hasDraft,
  onMic,
  onKeyboard,
}: ComposerControlsProps) {
  const { t } = useTranslation();
  const micDisabled = !recording && (!canCompose || typing);

  return (
    <div
      data-composer-keep=""
      className="absolute inset-x-0 flex justify-center gap-5 transition-[bottom] duration-300"
      style={{ bottom }}
    >
      <button
        type="button"
        aria-label={recording ? t('conversation.sendRecording') : t('conversation.record')}
        disabled={micDisabled}
        onClick={onMic}
        className={cn(
          'flex size-16 items-center justify-center rounded-full shadow-lg transition-all duration-200 active:scale-95',
          recording ? 'bg-recording hover:bg-recording-hover' : 'bg-accent',
          micDisabled && 'cursor-not-allowed opacity-40'
        )}
      >
        {recording ? (
          <SendHorizontal size={24} strokeWidth={2} className="text-white" />
        ) : (
          <Mic size={26} strokeWidth={2} className="text-accent-on" />
        )}
      </button>

      <button
        type="button"
        aria-label={typing ? t('conversation.sendText') : t('conversation.openKeyboard')}
        disabled={typing ? !hasDraft : !canCompose || recording}
        onClick={onKeyboard}
        className={cn(
          'flex size-16 items-center justify-center rounded-full border-2 transition-all duration-150 active:scale-95',
          typing
            ? hasDraft
              ? 'border-recording bg-recording hover:bg-recording-hover'
              : 'cursor-not-allowed border-recording bg-recording/60'
            : 'border-accent bg-surface-page'
        )}
      >
        {typing ? (
          <SendHorizontal size={22} strokeWidth={2} className="text-white" />
        ) : (
          <Keyboard size={22} strokeWidth={2} className="text-accent" />
        )}
      </button>
    </div>
  );
}
