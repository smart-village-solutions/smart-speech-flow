import { createContext, useContext } from 'react';
import type { AppConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createGuestTokenStore } from '@/core/http/guest-token-store';
import { createAudioOutput, type AudioOutput } from '@/core/audio/audio-output';
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
import { createAdminRepository } from '@/domain/admin/admin.repository';
import type { AdminRepository } from '@/domain/admin/admin.repository';
import { createHealthRepository } from '@/domain/health/health.repository';
import type { HealthRepository } from '@/domain/health/health.repository';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';
import type { BrandSource } from '@/domain/brand/brand.port';
import { createLoginTenantRepository } from '@/domain/login-tenant/loginTenant.repository';
import type { LoginTenantRepository } from '@/domain/login-tenant/loginTenant.repository';
import { createContentRepository } from '@/domain/content/content.repository';
import type { ContentSource } from '@/domain/content/content.port';
import type { ArchiveCrypto, KeyVault, PassphraseStrength } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';
import { createZxcvbnStrength } from '@/core/crypto/zxcvbn-strength';
import { createResumeMemory } from '@/core/storage/resume-memory';
import type { ResumeMemory } from '@/core/storage/resume-memory.port';
import { createRecordingKeysRepository } from '@/domain/recording/recording.repository';
import type { RecordingKeysRepository } from '@/domain/recording/recording.repository';

export interface Services {
  config: AppConfig;
  session: SessionRepository;
  language: LanguageRepository;
  message: MessageRepository;
  health: HealthRepository;
  admin: AdminRepository;
  loginTenant: LoginTenantRepository;
  content: ContentSource;
  feedback: FeedbackSink;
  brand: BrandSource;
  audio: AudioOutput;
  clips: ClipLoader;
  createRealtime: () => RealtimeTransport;
  recordingKeys: RecordingKeysRepository;
  archiveCrypto: ArchiveCrypto;
  keyVault: KeyVault;
  passphraseStrength: PassphraseStrength;
  resume: ResumeMemory;
}

/** The composition root. The only place implementations are chosen. */
export function createServices(config: AppConfig, getLocale: () => string): Services {
  // A sandboxed frame throws on merely reading localStorage, so the store reads it lazily.
  const guestTokens = createGuestTokenStore(() => globalThis.localStorage ?? null);
  const http = createHttpClient(config, getLocale, guestTokens);
  const admin = createAdminRepository(http);
  const session = createSessionRepository(http, guestTokens);
  const audio = createAudioOutput();

  return {
    config,
    session,
    language: createLanguageRepository(http),
    message: createMessageRepository(http, {
      pipelineTimeoutMs: config.pipelineTimeoutMs,
      apiBaseUrl: config.apiBaseUrl,
    }),
    feedback: createFeedbackRepository(http),
    health: createHealthRepository(http),
    admin,
    loginTenant: createLoginTenantRepository(http),
    content: createContentRepository(http),
    brand: createStaticBrandSource(config.brand),
    audio,
    clips: createBrowserClipLoader(http, audio),
    recordingKeys: createRecordingKeysRepository(http),
    archiveCrypto: createWebArchiveCrypto(),
    // Lives as long as these services: a reload or sign-out locks the keys.
    keyVault: createKeyVault(),
    passphraseStrength: createZxcvbnStrength(),
    resume: createResumeMemory(() => globalThis.sessionStorage ?? null),
    createRealtime: () =>
      createWebSocketTransport({
        wsBaseUrl: config.wsBaseUrl,
        issueTicket: (sessionId, role) =>
          role === 'admin'
            ? admin.issueRealtimeTicket(sessionId, 'websocket')
            : session.issueGuestTicket(sessionId),
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
