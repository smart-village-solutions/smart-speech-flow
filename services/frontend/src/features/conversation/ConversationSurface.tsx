import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { MessageBubble } from '@/ui/patterns/MessageBubble';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { ComposerBoxes } from './ComposerBoxes';
import { ComposerControls } from './ComposerControls';
import { ConversationStatus } from './ConversationStatus';
import type { ConversationScreenState } from './useConversationScreen';

interface ConversationSurfaceProps {
  screen: ConversationScreenState;
  header: ReactNode;
  /** A CSS length: where the chat stack starts below the shared fixed header. */
  contentTop: string;
  /** The admin's status pill. Rendered directly under the header. */
  overlay?: ReactNode;
  /** Recording's band, frame and question; each screen brings its own side. */
  recording?: ReactNode;
  /** The recording band is showing, so the stack and the pill sit below it. */
  recordingBand?: boolean;
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
  recording,
  recordingBand = false,
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
    legalBottom,
    legalBand,
    showsLegal,
    legalRef,
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
  // The recording band takes its height off the chat; nothing changes without it.
  const lessBand = (length: string) =>
    recordingBand ? `calc(${length} - var(--spacing-recording-band))` : length;
  const chatHeight = `50dvh - 36px - ${keyboardOffset}px - ${legalBand}`;

  return (
    <ScreenShell keyboardOpen={keyboardOffset > 0}>
      {header}
      {overlay}
      {recording}

      <div
        ref={chatRef}
        data-chat-stack=""
        className="absolute inset-x-0 overflow-y-auto transition-[max-height] duration-300"
        style={{
          top: recordingBand ? `calc(${contentTop} + var(--spacing-recording-band))` : contentTop,
          maxHeight: lessBand(`calc(${chatHeight})`),
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

      {/* Full width for centring only: taps on its empty sides reach the buttons. */}
      <div
        ref={legalRef}
        data-legal-row=""
        hidden={!showsLegal}
        className="pointer-events-none absolute inset-x-0 px-5 transition-[bottom] duration-300 [&_a]:pointer-events-auto"
        style={{ bottom: legalBottom }}
      >
        <SiteLegalLinks />
      </div>

      <ConversationStatus
        ended={state.ended}
        timeoutAt={state.timeoutAt}
        connection={state.connection}
        hasConnected={state.hasConnected}
        errorKey={state.errorKey}
        onRetry={retryLast}
        belowBand={recordingBand}
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
