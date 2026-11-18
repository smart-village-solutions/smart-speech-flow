import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { TextField } from '@/ui/primitives/TextField';
import { readPassphraseFile } from './passphrase-file';

export function PassphraseImport({
  onLoad,
  disabled,
}: Readonly<{ onLoad: (passphrase: string) => void; disabled: boolean }>) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current += 1;
    },
    []
  );
  return (
    <TextField
      type="file"
      accept=".txt,text/plain"
      label={t('admin.keys.files.import')}
      disabled={disabled}
      error={failed ? t('admin.keys.files.importFailed') : null}
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
  );
}
