import { useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { useServices } from '@/app/providers/services';
import { Button } from '@/ui/primitives/Button';
import { cn } from '@/lib/cn';
import type { ConversationUsage } from '@/domain/admin/usage';
import { useStaffLocalisation } from './useStaffLocalisation';

const SCOPES = ['personal', 'organisation', 'server'] as const;

/** Conversation totals with an optional breakdown by language. */
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
        <h2 id={headingId} className="text-body font-semibold text-fg-strong">
          {t('admin.usage.title')}
        </h2>
        <p className="rounded-lg bg-surface-status px-2.5 py-1 text-caption text-fg-muted">
          {t('admin.usage.period')}
        </p>
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
      <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3">
        {SCOPES.map((scope) => (
          <div
            key={scope}
            className={cn(
              'min-w-0 rounded-xl px-3 py-2.5',
              scope === 'personal' && 'col-span-full bg-accent-10 sm:col-span-1'
            )}
          >
            <dt className="text-label font-medium text-fg-muted">{t(`admin.usage.${scope}`)}</dt>
            <dd className="break-words text-title font-semibold tabular-nums text-fg-strong">
              {t('admin.tasks.minutes', { n: minutes(data[scope].total_seconds) })}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-caption text-fg-muted">{t('admin.usage.definition')}</p>
        <Button
          variant="compact"
          aria-expanded={expanded}
          aria-controls={detailsId}
          onClick={onToggle}
          className="min-h-11 border border-border-card px-4 text-label text-fg-strong hover:bg-surface-row-hover"
        >
          <ChevronDown aria-hidden size={16} className={expanded ? 'rotate-180' : ''} />
          {t(expanded ? 'admin.usage.hideLanguages' : 'admin.usage.showLanguages')}
        </Button>
      </div>
      <div id={detailsId} hidden={!expanded}>
        {expanded && (
          <table
            aria-labelledby={headingId}
            className="mt-3 w-full table-fixed text-note tabular-nums text-fg-strong"
          >
            <thead className="text-caption text-fg-muted">
              <tr>
                <th scope="col" className="w-1/4 py-2 text-start font-medium">
                  {t('admin.usage.language')}
                </th>
                {SCOPES.map((scope) => (
                  <th key={scope} scope="col" className="break-words py-2 text-end font-medium">
                    {scope === 'organisation' ? (
                      <>
                        <span className="sr-only sm:not-sr-only">
                          {t('admin.usage.organisation')}
                        </span>
                        <span aria-hidden className="sm:hidden">
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
              {languages.map((code) => (
                <tr key={code} className="border-t border-border-card">
                  <th scope="row" className="break-words py-2 text-start font-normal">
                    {languageOf(code === 'unknown' ? null : code).name}
                  </th>
                  {SCOPES.map((scope) => (
                    <td key={scope} className="break-words py-2 text-end">
                      {minutes(data[scope].by_language[code] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
              {languages.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-2 text-fg-muted">
                    {t('admin.usage.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
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
