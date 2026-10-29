import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ObjectNotStoredError } from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { Button } from '@/ui/primitives/Button';
import { useObjectOpener } from './useArchive';

interface AudioButtonProps {
  opened: OpenedConversation;
  keys: ReadonlyMap<string, CryptoKey>;
  entryId: string;
  objectType: 'original.wav' | 'translated.wav';
}

type Failure = 'notStored' | 'damaged';

/** Audio is fetched and decrypted on demand, and its Blob URL revoked when the viewer closes. */
export function AudioButton({ opened, keys, entryId, objectType }: Readonly<AudioButtonProps>) {
  const { t } = useTranslation();
  const openObject = useObjectOpener();
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  // A decryption that finishes after the viewer closed must not leave a Blob URL behind.
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url]
  );

  const load = async () => {
    setLoading(true);
    setFailure(null);
    try {
      const audio = await openObject(opened, keys, entryId, objectType);
      if (!mounted.current) return;
      setUrl(URL.createObjectURL(new Blob([audio], { type: 'audio/wav' })));
    } catch (error) {
      if (mounted.current)
        setFailure(error instanceof ObjectNotStoredError ? 'notStored' : 'damaged');
    } finally {
      if (mounted.current) setLoading(false);
    }
  };

  const label =
    objectType === 'original.wav'
      ? 'admin.archive.audio.original'
      : 'admin.archive.audio.translated';
  if (url !== null) {
    return (
      <audio controls src={url} className="w-full" aria-label={t(label)}>
        <track kind="captions" />
      </audio>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <Button variant="compact" onClick={() => void load()} disabled={loading}>
        {t(loading ? 'admin.archive.audio.loading' : label)}
      </Button>
      {failure !== null && (
        <span className="text-label text-fg-status-alert">
          {t(`admin.archive.entry.${failure}`)}
        </span>
      )}
    </div>
  );
}
