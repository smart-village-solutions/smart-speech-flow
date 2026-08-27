import { createContext, useContext } from 'react';
import type { AppConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createWebSocketTransport } from '@/core/realtime/WebSocketTransport';
import type { RealtimeTransport } from '@/core/realtime/realtime.port';
import { createSessionRepository } from '@/domain/session/session.repository';
import type { SessionRepository } from '@/domain/session/session.repository';
import { createLanguageRepository } from '@/domain/language/language.repository';
import type { LanguageRepository } from '@/domain/language/language.repository';
import { createMessageRepository } from '@/domain/message/message.repository';
import type { MessageRepository } from '@/domain/message/message.repository';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import type { FeedbackSink } from '@/domain/feedback/feedback.port';
import { createStubConsentSink } from '@/domain/consent/StubConsentSink';
import type { ConsentSink } from '@/domain/consent/consent.port';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';
import type { BrandSource } from '@/domain/brand/brand.port';

export interface Services {
  config: AppConfig;
  session: SessionRepository;
  language: LanguageRepository;
  message: MessageRepository;
  feedback: FeedbackSink;
  consent: ConsentSink;
  brand: BrandSource;
  createRealtime: () => RealtimeTransport;
}

/** The composition root. The only place implementations are chosen. */
export function createServices(config: AppConfig, getLocale: () => string): Services {
  const http = createHttpClient(config, getLocale);

  return {
    config,
    session: createSessionRepository(http),
    language: createLanguageRepository(http),
    message: createMessageRepository(http, {
      pipelineTimeoutMs: config.pipelineTimeoutMs,
      apiBaseUrl: config.apiBaseUrl,
    }),
    feedback: createStubFeedbackSink(),
    consent: createStubConsentSink(),
    brand: createStaticBrandSource(config.brand),
    createRealtime: () => createWebSocketTransport({ wsBaseUrl: config.wsBaseUrl }),
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
