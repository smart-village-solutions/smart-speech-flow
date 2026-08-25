import { useEffect, useRef, type RefObject } from 'react';
import { usePlayback } from '@/app/providers/playback';
import { useAudioRecorder } from '@/core/audio/useAudioRecorder';
import type { ChatMessage } from '@/domain/message/message.types';
import { hasConversationStatus } from './conversation.status';
import { useComposer } from './useComposer';
import { useConversation } from './useConversation';
import { useConversationPlayback } from './useConversationPlayback';
import { useKeyboardOffset } from './useKeyboardOffset';
import { useLatestRef } from './useLatestRef';
import { useSendFlight } from './useSendFlight';
import { useSessionLanguages } from './useSessionLanguages';

/** Keeps the newest message in view as the stack grows. */
function useScrollToLatest(ref: RefObject<HTMLDivElement | null>, messages: ChatMessage[]): void {
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [ref, messages]);
}

/**
 * Everything the conversation screen needs to be wired up, so the screen itself
 * is only markup. This is the one place where the session, the socket, the
 * recorder, the player and the send flight meet; holding that in the component
 * made it the largest file in the feature.
 */
export function useConversationScreen(sessionId: string) {
  const playback = usePlayback();
  const languages = useSessionLanguages(sessionId);
  const keyboardOffset = useKeyboardOffset();
  const chatRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const { state, dispatch, sendText, sendAudio, retryLast } = useConversation(
    sessionId,
    languages,
    { onPeerAudio: playback.enqueue }
  );

  const { flight, sourceRef, launch } = useSendFlight(chatRef);

  const bottom = `calc(${keyboardOffset}px + max(var(--spacing-mic-bottom), env(safe-area-inset-bottom)))`;
  // The recorder callback runs outside render, so the offset it launches from
  // is mirrored into a ref after each commit.
  const bottomRef = useLatestRef(bottom);

  const recorder = useAudioRecorder({
    onComplete: (wav) => {
      launch('recording', bottomRef.current);
      void sendAudio(wav);
    },
    // Not a failed send: nothing left the device, so there is nothing to repeat.
    onError: () => dispatch({ type: 'error/raised', errorKey: 'conversation.micDenied' }),
  });

  const isTyping = state.composer === 'typing';
  const isRecording = recorder.phase === 'recording';

  useScrollToLatest(chatRef, state.messages);
  useConversationPlayback(isRecording, playback);

  const composer = useComposer({
    sending: state.sending,
    ended: state.ended,
    isTyping,
    isRecording,
    recorder,
    composerRef,
    bottom,
    dispatch,
    launch,
    sendText,
  });

  return {
    ...composer,
    state,
    recorder,
    retryLast,
    flight,
    chatRef,
    composerRef,
    sourceRef,
    keyboardOffset,
    bottom,
    isTyping,
    isRecording,
    // The pill floats over the top of the stack, so the stack keeps clear of it.
    showsStatus: hasConversationStatus(state),
  };
}
