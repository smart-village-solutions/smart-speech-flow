import { useId, type HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { STATUS_TONES, type StatusTone } from '@/ui/primitives/statusTones';

interface InlineAlertProps extends HTMLAttributes<HTMLDivElement> {
  tone?: StatusTone;
}

/** Failures announce urgently; other live notices use status. Pass role="note" for static copy. */
export function InlineAlert({
  tone = 'neutral',
  title,
  children,
  className,
  role,
  ...props
}: Readonly<InlineAlertProps>) {
  const titleId = useId();
  return (
    <div
      role={role ?? (tone === 'danger' ? 'alert' : 'status')}
      aria-labelledby={title ? titleId : undefined}
      className={cn(
        'flex flex-col gap-2 rounded-2xl border p-4 text-note leading-chat',
        STATUS_TONES[tone],
        className
      )}
      {...props}
    >
      {title && (
        <p id={titleId} className="font-medium">
          {title}
        </p>
      )}
      {children !== undefined && children !== null && <div>{children}</div>}
    </div>
  );
}
