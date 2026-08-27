export function TypingDots() {
  return (
    <div
      data-testid="typing-dots"
      className="flex h-6 items-end gap-[2px] text-dots font-bold leading-none text-fg-muted"
    >
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="inline-block"
          style={{ animation: `bounce-dot 1s ease-in-out ${index * 0.18}s infinite` }}
        >
          .
        </span>
      ))}
    </div>
  );
}
