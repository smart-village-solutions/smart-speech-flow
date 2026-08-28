import type { AxiosInstance } from 'axios';
import { toSystemLoad } from './health.mapper';
import type { HealthSummaryDto } from './health.mapper';
import type { SystemLoad } from './health.types';

export interface HealthRepository {
  getSystemLoad(): Promise<SystemLoad>;
}

export function createHealthRepository(http: AxiosInstance): HealthRepository {
  return {
    async getSystemLoad() {
      const response = await http.get<HealthSummaryDto>('/api/health/summary');
      return toSystemLoad(response.data);
    },
  };
}
