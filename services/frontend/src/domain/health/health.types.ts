/**
 * The dashboard traffic light. `unknown` covers a failed or empty response, so
 * an unreachable gateway is never shown as available.
 */
export type SystemLoadLevel = 'ok' | 'delayed' | 'unavailable' | 'unknown';

export interface SystemLoad {
  level: SystemLoadLevel;
}
