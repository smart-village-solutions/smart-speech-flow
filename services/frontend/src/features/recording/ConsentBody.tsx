import { useTranslation } from 'react-i18next';
import type { ConsentText } from '@/domain/recording/recordingSession.types';
import { RichText } from '@/ui/patterns/RichText';

export interface ReadAloud {
  available: boolean;
  reading: boolean;
  toggle: () => Promise<void>;
}

interface ConsentBodyProps {
  text: ConsentText | null;
  failed: boolean;
  voice: ReadAloud;
}

/** The consent text as served, with its read-aloud control, or why it is not there yet. */
export function ConsentBody({ text, failed, voice }: Readonly<ConsentBodyProps>) {
  const { t, i18n } = useTranslation();

  if (text === null) {
    return (
      <p className="mt-2 text-note leading-chat text-fg-muted">
        {t(failed ? 'recording.consent.unavailable' : 'recording.consent.loading')}
      </p>
    );
  }
  return (
    <>
      {voice.available && (
        <button
          type="button"
          onClick={() => void voice.toggle()}
          className="mt-2 text-label font-medium text-fg-link"
        >
          {t(voice.reading ? 'recording.consent.stopReading' : 'recording.consent.readAloud')}
        </button>
      )}
      {text.language.split('-')[0] !== i18n.language.split('-')[0] && (
        <p className="mt-2 text-note text-fg-muted">
          {t('recording.consent.originalLanguage', { language: text.language })}
        </p>
      )}
      <div
        lang={text.language}
        className="mt-2 flex flex-col gap-3 text-note leading-chat text-fg-muted"
      >
        <RichText html={text.html} />
      </div>
    </>
  );
}
