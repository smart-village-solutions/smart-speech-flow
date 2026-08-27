interface CodeDisplayProps {
  code: string;
  /** The whole code as one phrase, e.g. "Sitzungscode A1B2C3D4". */
  label: string;
}

/**
 * The read-only counterpart to `CodeInput`: the invite code the admin reads out
 * and the customer types in. Eight boxes of static text, so it shares no
 * behaviour with the input — only the idea of a box.
 *
 * The boxes are hidden from assistive technology and the code is announced once
 * as a phrase instead. Eight separate characters read aloud one at a time is not
 * a code anyone can write down.
 */
export function CodeDisplay({ code, label }: Readonly<CodeDisplayProps>) {
  // The position in the code is the box's identity, which is why it is named
  // rather than keyed by array index.
  const boxes = [...code.toUpperCase()].map((character, index) => ({
    id: `code-char-${index}`,
    character,
  }));

  return (
    <div dir="ltr" className="flex w-full justify-center gap-2">
      <span className="sr-only">{label}</span>

      {boxes.map((box) => (
        <span
          key={box.id}
          data-code-box=""
          aria-hidden
          className="flex h-code-lg w-full min-w-0 max-w-code-lg shrink items-center justify-center rounded-row border-2 border-accent-40 bg-surface-code-box text-code-lg font-semibold text-fg-strong"
        >
          {box.character}
        </span>
      ))}
    </div>
  );
}
