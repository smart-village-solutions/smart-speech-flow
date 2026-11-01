export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger';

export const STATUS_TONES: Record<StatusTone, string> = {
  neutral: 'border-border-status bg-surface-status text-fg-body',
  success: 'border-border-success bg-surface-success text-fg-success',
  warning: 'border-border-warning bg-surface-warning text-fg-warning',
  danger: 'border-border-status-alert bg-surface-alert text-fg-status-alert',
};
