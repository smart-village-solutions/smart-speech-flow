import { useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useServices } from '@/app/providers/services';
import type { ConversationUsage } from '@/domain/admin/usage';
import { useStaffLocalisation } from './useStaffLocalisation';

const SCOPES = ['personal', 'organisation', 'server'] as const;

/** One compact summary, with the same columns used for optional language detail. */
export function ConversationUsageCard() {
  const { admin } = useServices();
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const headingId = useId();
  // The administrative route owns and clears its cache on exit or tenant change.
  const { data, isError } = useQuery({
    queryKey: ['conversationUsage'],
    queryFn: () => admin.getUsage(),
    refetchInterval: 30_000,
  });

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2
          id={headingId}
          className="text-caption font-semibold uppercase tracking-widest text-fg-muted"
        >
          {t('admin.usage.title')}
        </h2>
        <p className="text-caption text-fg-muted">{t('admin.usage.period')}</p>
      </div>
      {isError ? (
        <p role="alert" className="mt-3 text-note text-fg-muted">
          {t('admin.usage.unavailable')}
        </p>
      ) : data === undefined ? (
        <p role="status" className="mt-3 text-note text-fg-muted">
          {t('admin.usage.loading')}
        </p>
      ) : (
        <ConversationUsageSummary
          data={data}
          headingId={headingId}
          expanded={expanded}
          onToggle={() => setExpanded((value) => !value)}
        />
      )}
    </section>
  );
}

/** The loaded summary and its optional language details share the same columns. */
function ConversationUsageSummary({
  data,
  headingId,
  expanded,
  onToggle,
}: {
  data: ConversationUsage;
  headingId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { languageOf, timeZone } = useStaffLocalisation();
  const detailsId = useId();
  const minutes = (value: number) =>
    new Intl.NumberFormat(i18n.language, {
      maximumFractionDigits: 1,
    }).format(value / 60);
  const languages = [
    ...new Set(SCOPES.flatMap((scope) => Object.keys(data[scope].by_language))),
  ].sort(
    (a, b) =>
      (data.server.by_language[b] ?? 0) - (data.server.by_language[a] ?? 0) || a.localeCompare(b)
  );

  return (
    <>
      <table
        aria-labelledby={headingId}
        className="mt-3 w-full table-fixed text-note tabular-nums text-fg-strong"
      >
        <thead className="text-caption text-fg-muted">
          <tr>
            <th scope="col" className="w-1/4 text-start font-normal">
              <span className="sr-only">{t('admin.usage.language')}</span>
            </th>
            {SCOPES.map((scope) => (
              <th key={scope} scope="col" className="py-1 text-end font-normal break-words">
                {scope === 'organisation' ? (
                  <>
                    <span className="sr-only sm:not-sr-only">{t('admin.usage.organisation')}</span>
                    <span aria-hidden="true" className="sm:hidden">
                      {t('admin.usage.organisationShort')}
                    </span>
                  </>
                ) : (
                  t(`admin.usage.${scope}`)
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="font-semibold">
            <th scope="row" className="py-2 text-start">
              {t('admin.usage.total')}
            </th>
            {SCOPES.map((scope) => (
              <td key={scope} className="py-2 text-end">
                {minutes(data[scope].total_seconds)}
              </td>
            ))}
          </tr>
        </tbody>
        <tbody id={detailsId}>
          {expanded &&
            languages.map((code) => (
              <tr key={code} className="border-t border-border-card">
                <th scope="row" className="py-2 text-start font-normal break-words">
                  {languageOf(code === 'unknown' ? null : code).name}
                </th>
                {SCOPES.map((scope) => (
                  <td key={scope} className="py-2 text-end">
                    {minutes(data[scope].by_language[code] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          {expanded && languages.length === 0 && (
            <tr>
              <td colSpan={4} className="py-2 text-fg-muted">
                {t('admin.usage.empty')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={onToggle}
        className="focus-ring hit-target mt-1 inline-flex items-center gap-1 rounded-lg text-caption text-fg-muted"
      >
        <ChevronDown aria-hidden="true" size={16} className={expanded ? 'rotate-180' : ''} />
        {t(expanded ? 'admin.usage.hideLanguages' : 'admin.usage.showLanguages')}
      </button>
      <p className="mt-1 text-caption text-fg-muted">{t('admin.usage.definition')}</p>
      {!data.complete && (
        <p className="mt-1 text-caption text-fg-muted">
          {t('admin.usage.coverage', {
            date: new Intl.DateTimeFormat(i18n.language, {
              dateStyle: 'short',
              timeZone: timeZone ?? undefined,
            }).format(new Date(data.coverage_start)),
          })}
        </p>
      )}
    </>
  );
}
