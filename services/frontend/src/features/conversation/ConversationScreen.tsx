import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { usePlayback } from '@/app/providers/playback';
import { useQuery } from '@tanstack/react-query';
import { useScreenLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';
import { useAudioRecorder } from '@/core/audio/useAudioRecorder';
import { cn } from '@/lib/cn';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { MessageBubble } from '@/ui/patterns/MessageBubble';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { ComposerBoxes } from './ComposerBoxes';
import { ComposerControls } from './ComposerControls';
import { ConversationStatus } from './ConversationStatus';
import { hasConversationStatus } from './conversation.status';
import { useConversation } from './useConversation';
import { useDismissOnOutsideTap } from './useDismissOnOutsideTap';
import { useKeyboardOffset } from './useKeyboardOffset';
import { useSendFlight } from './useSendFlight';

export function ConversationScreen() {
  const { openFeedback } = useFeedback();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { session } = useServices();
  const { enqueue, stop: stopPlayback, hold, release } = usePlayback();
  const keyboardOffset = useKeyboardOffset();
  const chatRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const [draft, setDraft] = useState('');

  const sessionQuery = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId as string),
  });

  // The url carries no language code, so the session is what says which one
  // the customer reads. Nothing is declared until the query answers.
  useScreenLocale(sessionQuery.data?.customerLanguage ?? '');

  const customerLanguage = sessionQuery.data?.customerLanguage ?? 'en';
  const adminLanguage = sessionQuery.data?.adminLanguage ?? 'de';

  const { state, dispatch, sendText, sendAudio, retryLast } = useConversation(
    sessionId as string,
    { source: customerLanguage, target: adminLanguage },
    { onPeerAudio: enqueue }
  );

  const { flight, sourceRef, launch } = useSendFlight(chatRef);

  // The recorder callback runs outside render, so the offset it launches from
  // is mirrored into a ref after each commit.
  const bottomRef = useRef('');

  const recorder = useAudioRecorder({
    onComplete: (wav) => {
      launch('recording', bottomRef.current);
      void sendAudio(wav);
    },
    onError: () =>
      dispatch({ type: 'send/failed', tempId: '', errorKey: 'conversation.micDenied' }),
  });

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight });
  }, [state.messages]);

  // Leaving the conversation silences it; the player outlives this screen.
  useEffect(() => stopPlayback, [stopPlayback]);

  // The pill floats over the top of the stack, so the stack keeps clear of it.
  const showsStatus = hasConversationStatus(state);

  const isTyping = state.composer === 'typing';
  const isRecording = recorder.phase === 'recording';

  // A tap outside puts the composer away, which is what frees the mic again.
  // The draft is kept, so reopening the keyboard picks up where it left off.
  const closeComposer = useCallback(
    () => dispatch({ type: 'composer/mode', mode: 'idle' }),
    [dispatch]
  );
  useDismissOnOutsideTap(isTyping, closeComposer);

  // Nothing is spoken aloud into an open microphone: arrivals queue instead,
  // and whatever was playing is replayed in full once the mic closes.
  useEffect(() => {
    if (!isRecording) {
      return;
    }
    hold();
    return release;
  }, [isRecording, hold, release]);
  const canCompose = !state.sending && !state.ended;
  const bottom = `calc(${keyboardOffset}px + max(var(--spacing-mic-bottom), env(safe-area-inset-bottom)))`;

  useEffect(() => {
    bottomRef.current = bottom;
  });

  const submitDraft = () => {
    const text = draft.trim();
    if (!text || !canCompose) {
      return;
    }
    launch('typing', bottom);
    setDraft('');
    dispatch({ type: 'composer/mode', mode: 'idle' });
    void sendText(text);
  };

  return (
    <ScreenShell>
      <AppHeader
        onBack={() => void navigate(`/s/${sessionId}/language`)}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
      />

      <div
        ref={chatRef}
        className="absolute inset-x-0 overflow-y-auto transition-[max-height] duration-300"
        style={{
          top: 'var(--spacing-header)',
          maxHeight: `calc(50dvh - 36px - ${keyboardOffset}px)`,
        }}
      >
        <div className={cn('flex flex-col gap-3 pb-4', showsStatus ? 'pt-14' : 'pt-4')}>
          {state.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>
      </div>

      <ComposerBoxes
        bottom={flight?.bottom ?? bottom}
        flight={flight}
        sourceRef={sourceRef}
        composerRef={composerRef}
        recording={isRecording}
        levels={recorder.levels}
        elapsedSeconds={recorder.elapsedSeconds}
        typing={isTyping}
        draft={draft}
        onDraftChange={setDraft}
        onSubmit={submitDraft}
        onCancel={() => {
          setDraft('');
          dispatch({ type: 'composer/mode', mode: 'idle' });
        }}
      />

      <ComposerControls
        bottom={bottom}
        recording={isRecording}
        typing={isTyping}
        canCompose={canCompose}
        hasDraft={draft.trim() !== ''}
        onMic={() => {
          if (isRecording) {
            recorder.stop();
            return;
          }
          dispatch({ type: 'composer/mode', mode: 'recording' });
          void recorder.start();
        }}
        onKeyboard={() => {
          if (isTyping) {
            submitDraft();
            return;
          }
          dispatch({ type: 'composer/mode', mode: 'typing' });
          window.setTimeout(() => composerRef.current?.focus(), 50);
        }}
      />

      <ConversationStatus
        ended={state.ended}
        connection={state.connection}
        hasConnected={state.hasConnected}
        errorKey={state.errorKey}
        onRetry={retryLast}
      />
    </ScreenShell>
  );
}
