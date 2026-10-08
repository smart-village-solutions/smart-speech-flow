const BARS = ['intro', 'howTo', 'retention', 'optIn'] as const;

/** Holds the prose block's place while guest content loads, so no legal text is shown twice. */
export function ConsentSkeleton({ label }: Readonly<{ label: string }>) {
  return (
    // <output> carries role="status" itself, so the role attribute is redundant.
    <output aria-label={label} aria-busy="true" className="flex flex-col gap-5">
      {BARS.map((bar) => (
        <span key={bar} className="block h-20 animate-pulse rounded-box bg-surface-field" />
      ))}
    </output>
  );
}
