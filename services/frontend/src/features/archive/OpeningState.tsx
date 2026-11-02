import { useTranslation } from 'react-i18next';

type NotReady =
  | { status: 'checking' }
  | { status: 'unavailable' }
  | { status: 'broken'; stage: string };

interface OpeningStateProps {
  state: NotReady;
  /** The screen's own "could not load" text. */
  unavailable: string;
}

/** While the checks of spec §10.6 run, or after they failed: nothing of the content renders. */
export function OpeningState({ state, unavailable }: Readonly<OpeningStateProps>) {
  const { t } = useTranslation();
  if (state.status === 'checking')
    return <p className="text-note text-fg-muted">{t('admin.archive.checking')}</p>;
  if (state.status === 'unavailable') {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t(unavailable)}
      </p>
    );
  }
  return (
    <div role="alert" className="rounded-2xl border border-border-status bg-surface-card p-5">
      <h2 className="mb-1.5 text-body font-semibold text-fg-strong">
        {t('admin.archive.integrity.title')}
      </h2>
      <p className="text-note text-fg-muted">{t(`admin.archive.integrity.${state.stage}`)}</p>
    </div>
  );
}
