import { z } from 'zod';

const seconds = z.number().finite().nonnegative();
const scope = z.object({
  total_seconds: seconds,
  by_language: z.record(z.string(), seconds),
});

export const conversationUsageSchema = z.object({
  window_start: z.string().datetime({ offset: true }),
  window_end: z.string().datetime({ offset: true }),
  coverage_start: z.string().datetime({ offset: true }),
  complete: z.boolean(),
  personal: scope,
  organisation: scope,
  server: scope,
});

export type ConversationUsage = z.infer<typeof conversationUsageSchema>;
