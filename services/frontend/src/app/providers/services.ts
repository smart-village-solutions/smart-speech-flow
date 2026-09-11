import { createContext, useContext } from 'react';
import type { AppConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createBrowserClipLoader, type ClipLoader } from '@/core/audio/clips';
import { createWebSocketTransport } from '@/core/realtime/WebSocketTransport';
import type { RealtimeTransport } from '@/core/realtime/realtime.port';
import { createSessionRepository } from '@/domain/session/session.repository';
import type { SessionRepository } from '@/domain/session/session.repository';
import { createLanguageRepository } from '@/domain/language/language.repository';
import type { LanguageRepository } from '@/domain/language/language.repository';
import { createMessageRepository } from '@/domain/message/message.repository';
import type { MessageRepository } from '@/domain/message/message.repository';
import { createFeedbackRepository } from '@/domain/feedback/feedback.repository';
import type { FeedbackSink } from '@/domain/feedback/feedback.port';
import { createStubConsentSink } from '@/domain/consent/StubConsentSink';
import type { ConsentSink } from '@/domain/consent/consent.port';
import { createAdminRepository } from '@/domain/admin/admin.repository';
import type { AdminRepository } from '@/domain/admin/admin.repository';
import { createHealthRepository } from '@/domain/health/health.repository';
import type { HealthRepository } from '@/domain/health/health.repository';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';
import type { BrandSource } from '@/domain/brand/brand.port';
import { createLoginTenantRepository } from '@/domain/login-tenant/loginTenant.repository';
import type { LoginTenantRepository } from '@/domain/login-tenant/loginTenant.repository';

export interface Services {
  config: AppConfig;
  session: SessionRepository;
  language: LanguageRepository;
  message: MessageRepository;
  health: HealthRepository;
  admin: AdminRepository;
  loginTenant: LoginTenantRepository;
  feedback: FeedbackSink;
  consent: ConsentSink;
  brand: BrandSource;
  clips: ClipLoader;
  createRealtime: () => RealtimeTransport;
}

/** The composition root. The only place implementations are chosen. */
export function createServices(config: AppConfig, getLocale: () => string): Services {
  const http = createHttpClient(config, getLocale);
  const admin = createAdminRepository(http);

  return {
    config,
    session: createSessionRepository(http),
    language: createLanguageRepository(http),
    message: createMessageRepository(http, {
      pipelineTimeoutMs: config.pipelineTimeoutMs,
      apiBaseUrl: config.apiBaseUrl,
    }),
    feedback: createFeedbackRepository(http),
    consent: createStubConsentSink(),
    health: createHealthRepository(http),
    admin,
    loginTenant: createLoginTenantRepository(http),
    brand: createStaticBrandSource(config.brand),
    clips: createBrowserClipLoader(http),
    createRealtime: () =>
      createWebSocketTransport({
        wsBaseUrl: config.wsBaseUrl,
        issueAdminTicket: (sessionId, transport) =>
          admin.issueRealtimeTicket(sessionId, transport),
      }),
  };
}

const ServicesContext = createContext<Services | null>(null);

export { ServicesContext };

export function useServices(): Services {
  const value = useContext(ServicesContext);

  if (value === null) {
    throw new Error('useServices must be used inside a ServicesProvider');
  }

  return value;
}
