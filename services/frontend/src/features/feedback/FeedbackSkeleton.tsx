const BARS = ['first', 'second', 'third'] as const;

/** Holds the form body's place while the audience's content loads, so no form is swapped. */
export function FeedbackSkeleton({ label }: Readonly<{ label: string }>) {
  return (
    // <output> carries role="status" itself, so the role attribute is redundant.
    <output aria-label={label} aria-busy="true" className="flex flex-col gap-6 px-5 pb-8 pt-5">
      {BARS.map((bar) => (
        <span key={bar} className="block h-20 animate-pulse rounded-box bg-surface-field" />
      ))}
    </output>
  );
}
