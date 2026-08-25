import { useRef } from 'react';
import type { ClipboardEvent, KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CODE_LENGTH } from '@/lib/accessCode';
import { cn } from '@/lib/cn';

interface CodeInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
}

export function CodeInput({ value, onChange, length = CODE_LENGTH }: Readonly<CodeInputProps>) {
  const { t } = useTranslation();
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  // Each box is a fixed position in the code, so the position IS its identity.
  // Named rather than keyed by index, which reads as an accidental key.
  const boxes = Array.from({ length }, (_, index) => {
    const character = value[index];
    return {
      id: `code-box-${index}`,
      character: character && character !== ' ' ? character : '',
    };
  });
  const characters = boxes.map((box) => box.character);

  const focusAt = (index: number) => {
    if (index >= 0 && index < length) {
      inputs.current[index]?.focus();
    }
  };

  const writeAt = (index: number, character: string) => {
    const next = [...characters];
    next[index] = character;
    onChange(next.map((entry) => entry || ' ').join(''));
  };

  const handleChange = (index: number, raw: string) => {
    const character = raw.replace(/\s/g, '').slice(-1).toUpperCase();
    writeAt(index, character);

    if (character) {
      focusAt(index + 1);
    }
  };

  const handleKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace') {
      if (characters[index]) {
        writeAt(index, '');
      } else {
        focusAt(index - 1);
      }
    } else if (event.key === 'ArrowLeft') {
      focusAt(index - 1);
    } else if (event.key === 'ArrowRight') {
      focusAt(index + 1);
    }
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    const pasted = event.clipboardData
      .getData('text')
      .replace(/\s/g, '')
      .slice(0, length)
      .toUpperCase();

    if (!pasted) {
      return;
    }

    onChange(pasted.padEnd(length, ' '));
    focusAt(Math.min(pasted.length, length - 1));
  };

  return (
    <div dir="ltr" className="mb-10 flex w-full justify-center gap-2">
      {boxes.map((box, index) => (
        <input
          key={box.id}
          ref={(element) => {
            inputs.current[index] = element;
          }}
          type="text"
          inputMode="text"
          autoComplete="one-time-code"
          maxLength={1}
          value={box.character}
          onChange={(event) => handleChange(index, event.target.value)}
          onKeyDown={(event) => handleKeyDown(index, event)}
          onPaste={handlePaste}
          onFocus={(event) => event.target.select()}
          aria-label={t('accessCode.digitLabel', { position: index + 1 })}
          className={cn(
            // Boxes flex down on phones: eight at the design 46px cannot fit a
            // 390px viewport. Capped at 46px so wider screens match exactly.
            'h-code-h w-full min-w-0 max-w-code-w shrink rounded-box border-2 text-center',
            'text-code font-normal tracking-code caret-transparent outline-none',
            'bg-surface-code-box text-fg-strong transition-colors duration-150',
            box.character ? 'border-accent' : 'border-border-code-empty'
          )}
        />
      ))}
    </div>
  );
}
