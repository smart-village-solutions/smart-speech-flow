import { useCallback, useState, type RefObject } from 'react';
import type { AudioRecorderState } from '@/core/audio/useAudioRecorder';
import type { ConversationAction } from './conversation.reducer';
import type { SendFlight } from './useSendFlight';
import { useDismissOnOutsideTap } from './useDismissOnOutsideTap';

interface ComposerDeps {
  sending: boolean;
  ended: boolean;
  isTyping: boolean;
  isRecording: boolean;
  recorder: AudioRecorderState;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  bottom: string;
  dispatch: (action: ConversationAction) => void;
  launch: (kind: SendFlight['kind'], bottom: string) => void;
  sendText: (text: string) => Promise<void>;
}

/** The keyboard takes a moment to open; focusing sooner loses the caret. */
const FOCUS_DELAY_MS = 50;

/**
 * The draft and the four things the customer can do with the composer. Kept
 * apart from `useConversationScreen` because none of it needs the session, the
 * socket or the player — only the recorder and the reducer.
 */
export function useComposer(deps: ComposerDeps) {
  const [draft, setDraft] = useState('');
  const canCompose = !deps.sending && !deps.ended;

  const { dispatch } = deps;
  const close = useCallback(
    () => dispatch({ type: 'composer/mode', mode: 'idle' }),
    [dispatch]
  );

  // A tap outside puts the composer away, which is what frees the mic again.
  // The draft is kept, so reopening the keyboard picks up where it left off.
  useDismissOnOutsideTap(deps.isTyping, close);

  const submitDraft = () => {
    const text = draft.trim();
    if (text === '' || !canCompose) {
      return;
    }

    deps.launch('typing', deps.bottom);
    setDraft('');
    close();
    void deps.sendText(text);
  };

  const cancelDraft = () => {
    setDraft('');
    close();
  };

  const toggleMic = () => {
    if (deps.isRecording) {
      deps.recorder.stop();
      return;
    }

    deps.dispatch({ type: 'composer/mode', mode: 'recording' });
    void deps.recorder.start();
  };

  const toggleKeyboard = () => {
    if (deps.isTyping) {
      submitDraft();
      return;
    }

    deps.dispatch({ type: 'composer/mode', mode: 'typing' });
    window.setTimeout(() => deps.composerRef.current?.focus(), FOCUS_DELAY_MS);
  };

  return {
    draft,
    setDraft,
    canCompose,
    hasDraft: draft.trim() !== '',
    submitDraft,
    cancelDraft,
    toggleMic,
    toggleKeyboard,
  };
}
