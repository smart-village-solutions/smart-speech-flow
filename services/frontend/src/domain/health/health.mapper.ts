import type { SystemLoad } from './health.types';

/**
 * Every field is optional: the gateway builds this payload with `.get(…, default)`
 * throughout (`api_gateway/routes/circuit_breaker.py:351`), so absence is normal
 * rather than exceptional.
 */
export interface HealthSummaryDto {
  overall_healthy?: boolean;
  summary?: {
    service_mode?: string;
    circuit_states?: Record<string, string>;
    gpu?: {
      critical_devices?: number;
      warning_devices?: number;
      recommended_action?: string;
    };
  };
}

const DOWN_MODES = new Set(['minimal', 'offline']);

function isUnavailable(dto: HealthSummaryDto, circuits: string[]): boolean {
  const { service_mode: mode, gpu } = dto.summary ?? {};

  return (
    dto.overall_healthy === false ||
    DOWN_MODES.has(mode ?? '') ||
    (gpu?.critical_devices ?? 0) > 0 ||
    circuits.includes('open')
  );
}

function isDelayed(dto: HealthSummaryDto, circuits: string[]): boolean {
  const { service_mode: mode, gpu } = dto.summary ?? {};

  return (
    mode === 'degraded' ||
    (gpu?.warning_devices ?? 0) > 0 ||
    gpu?.recommended_action === 'scale_up' ||
    circuits.includes('half_open')
  );
}

export function toSystemLoad(dto: HealthSummaryDto): SystemLoad {
  if (dto.overall_healthy === undefined && dto.summary === undefined) {
    return { level: 'unknown' };
  }

  const circuits = Object.values(dto.summary?.circuit_states ?? {});

  if (isUnavailable(dto, circuits)) {
    return { level: 'unavailable' };
  }
  return { level: isDelayed(dto, circuits) ? 'delayed' : 'ok' };
}
