import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload } from 'lucide-react';
import { Button } from '@/ui/primitives/Button';
import { readPassphraseFile } from './passphrase-file';

export function PassphraseImport({
  onLoad,
  disabled,
}: Readonly<{ onLoad: (passphrase: string) => void; disabled: boolean }>) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current += 1;
    },
    []
  );
  return (
    <div className="min-w-0">
      <Button
        variant="compact"
        disabled={disabled}
        className="min-h-11 max-w-full border border-border-card px-4 text-label text-fg-strong hover:bg-surface-row-hover"
        onClick={() => input.current?.click()}
      >
        <Upload aria-hidden className="size-4 shrink-0" />
        {t('admin.keys.files.import')}
      </Button>
      <input
        ref={input}
        type="file"
        accept=".txt,text/plain"
        aria-label={t('admin.keys.files.import')}
        disabled={disabled}
        hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          const current = ++generation.current;
          setFailed(false);
          if (!file) return;
          void readPassphraseFile(file).then(
            (passphrase) => {
              if (current === generation.current) onLoad(passphrase);
            },
            () => {
              if (current === generation.current) setFailed(true);
            }
          );
        }}
      />
      {failed && (
        <p role="alert" className="mt-2 text-meta text-fg-status-alert">
          {t('admin.keys.files.importFailed')}
        </p>
      )}
    </div>
  );
}
