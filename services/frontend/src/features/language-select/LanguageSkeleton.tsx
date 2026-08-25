const PLACEHOLDER_ROWS = 6;

/**
 * The export has no loading state because its list is hardcoded. These rows
 * hold the real list's geometry (40px flag, two text lines) so the screen does
 * not jump when the gateway responds.
 */
export function LanguageSkeleton({ label }: { label: string }) {
  return (
    <ul role="status" aria-label={label} aria-busy="true" className="mx-auto flex max-w-sm flex-col gap-4">
      {Array.from({ length: PLACEHOLDER_ROWS }, (_, index) => (
        <li key={index} className="flex animate-pulse items-center gap-6 px-4 py-2">
          <span className="size-10 shrink-0 rounded-full bg-surface-field" />
          <span className="flex flex-1 flex-col gap-1">
            <span className="h-4 w-32 rounded-box bg-surface-field" />
            <span className="h-3 w-20 rounded-box bg-surface-field" />
          </span>
        </li>
      ))}
    </ul>
  );
}
