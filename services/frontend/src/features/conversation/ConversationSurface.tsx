import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { MessageBubble } from '@/ui/patterns/MessageBubble';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { ComposerBoxes } from './ComposerBoxes';
import { ComposerControls } from './ComposerControls';
import { ConversationStatus } from './ConversationStatus';
import type { ConversationScreenState } from './useConversationScreen';

interface ConversationSurfaceProps {
  screen: ConversationScreenState;
  header: ReactNode;
  /** A CSS length: where the chat stack starts. 72px customer, 128px admin. */
  contentTop: string;
  /** The admin's status pill. Rendered directly under the header. */
  overlay?: ReactNode;
  /**
   * Sits at the composer's unlifted baseline — the admin's terminate link. The
   * lift itself comes from `screen.composerLift`, applied inside `bottom` so the
   * send flight launches from the right place.
   */
  footer?: ReactNode;
}

/**
 * The chat stack, the composer and the status pill: everything both
 * conversations share. Extracted so the admin screen composes it rather than the
 * customer screen branching on an `adminMode` flag, which is how the export
 * keeps two screens in one function.
 */
export function ConversationSurface({
  screen,
  header,
  contentTop,
  overlay,
  footer,
}: Readonly<ConversationSurfaceProps>) {
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
    composerLift,
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
  } = screen;

  return (
    <ScreenShell>
      {header}
      {overlay}

      <div
        ref={chatRef}
        data-chat-stack=""
        className="absolute inset-x-0 overflow-y-auto transition-[max-height] duration-300"
        style={{
          top: contentTop,
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

      {footer === undefined ? null : (
        <div
          className="absolute inset-x-0 flex justify-center transition-[bottom] duration-300"
          style={{ bottom: `calc(${bottom} - ${composerLift})` }}
        >
          {footer}
        </div>
      )}
    </ScreenShell>
  );
}
