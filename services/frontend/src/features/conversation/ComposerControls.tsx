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

const CONTROL = 'flex size-16 items-center justify-center rounded-full active:scale-95';

function MicButton({
  recording,
  disabled,
  onClick,
}: Readonly<{ recording: boolean; disabled: boolean; onClick: () => void }>) {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      aria-label={recording ? t('conversation.sendRecording') : t('conversation.record')}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        CONTROL,
        'shadow-lg transition-all duration-200',
        recording ? 'bg-recording hover:bg-recording-hover' : 'bg-accent',
        disabled && 'cursor-not-allowed opacity-40'
      )}
    >
      {recording ? (
        <SendHorizontal size={24} strokeWidth={2} className="text-white" />
      ) : (
        <Mic size={26} strokeWidth={2} className="text-accent-on" />
      )}
    </button>
  );
}

/** While typing, the draft is what decides whether the control can send. */
function keyboardSkin(typing: boolean, hasDraft: boolean): string {
  if (!typing) {
    return 'border-accent bg-surface-page';
  }

  return hasDraft
    ? 'border-recording bg-recording hover:bg-recording-hover'
    : 'cursor-not-allowed border-recording bg-recording/60';
}

function KeyboardButton({
  typing,
  hasDraft,
  disabled,
  onClick,
}: Readonly<{ typing: boolean; hasDraft: boolean; disabled: boolean; onClick: () => void }>) {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      aria-label={typing ? t('conversation.sendText') : t('conversation.openKeyboard')}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        CONTROL,
        'border-2 transition-all duration-150',
        keyboardSkin(typing, hasDraft)
      )}
    >
      {typing ? (
        <SendHorizontal size={22} strokeWidth={2} className="text-white" />
      ) : (
        <Keyboard size={22} strokeWidth={2} className="text-accent" />
      )}
    </button>
  );
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
}: Readonly<ComposerControlsProps>) {
  return (
    <div
      data-dismiss-keep=""
      className="absolute inset-x-0 flex justify-center gap-5 transition-[bottom] duration-300"
      style={{ bottom }}
    >
      <MicButton
        recording={recording}
        disabled={!recording && (!canCompose || typing)}
        onClick={onMic}
      />
      <KeyboardButton
        typing={typing}
        hasDraft={hasDraft}
        disabled={typing ? !hasDraft : !canCompose || recording}
        onClick={onKeyboard}
      />
    </div>
  );
}
