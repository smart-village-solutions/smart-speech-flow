import { useNavigate, useParams } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { cn } from '@/lib/cn';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { MessageBubble } from '@/ui/patterns/MessageBubble';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { ComposerBoxes } from './ComposerBoxes';
import { ComposerControls } from './ComposerControls';
import { ConversationStatus } from './ConversationStatus';
import { useConversationScreen } from './useConversationScreen';

export function ConversationScreen() {
  const { openFeedback } = useFeedback();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();

  const {
    state,
    recorder,
    retryLast,
    flight,
    chatRef,
    composerRef,
    sourceRef,
    keyboardOffset,
    bottom,
    draft,
    setDraft,
    isTyping,
    isRecording,
    canCompose,
    hasDraft,
    showsStatus,
    submitDraft,
    cancelDraft,
    toggleMic,
    toggleKeyboard,
  } = useConversationScreen(sessionId as string);

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
        onCancel={cancelDraft}
      />

      <ComposerControls
        bottom={bottom}
        recording={isRecording}
        typing={isTyping}
        canCompose={canCompose}
        hasDraft={hasDraft}
        onMic={toggleMic}
        onKeyboard={toggleKeyboard}
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
