import type { ConsentText } from '@/domain/recording/recordingSession.types';
import { Checkbox } from '@/ui/primitives/Checkbox';

interface DocumentationConsentChoiceProps {
  text: ConsentText | null;
  accepted: boolean;
  onAccept: (accepted: boolean) => void;
  onDecline: () => void;
}

/** Documentation consent is a separate choice from releasing the recording section. */
export function DocumentationConsentChoice({
  text,
  accepted,
  onAccept,
  onDecline,
}: Readonly<DocumentationConsentChoiceProps>) {
  if (text?.documentationConsent == null) return null;
  return (
    <div lang={text.language} className="mt-4">
      <Checkbox checked={accepted} onCheckedChange={onAccept}>
        {text.documentationConsent.acceptLabel}
      </Checkbox>
      <button type="button" className="mt-2 text-label text-fg-link" onClick={onDecline}>
        {text.documentationConsent.declineLabel}
      </button>
    </div>
  );
}
