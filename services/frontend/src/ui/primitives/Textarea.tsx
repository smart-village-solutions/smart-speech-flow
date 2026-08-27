import type { Ref, TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  ref?: Ref<HTMLTextAreaElement>;
}

export function Textarea({ className, ...props }: Readonly<TextareaProps>) {
  return (
    <textarea
      className={cn(
        'w-full resize-none bg-transparent text-body leading-chat text-fg-chat outline-none placeholder:text-fg-placeholder',
        className
      )}
      {...props}
    />
  );
}
