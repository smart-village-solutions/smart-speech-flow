import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);

// A response that lands after its file's jsdom is torn down throws outside any
// test ("ProgressEvent is not defined"), and only on a slow enough runner. A
// request that outlives its test fails that test instead, on every machine.
const inFlight = new Map<string, string>();
const track = ({ request, requestId }: { request: Request; requestId: string }) => {
  inFlight.set(requestId, `${request.method} ${new URL(request.url).pathname}`);
};
// A throwing handler and an unhandled request never emit request:end.
const settle = ({ requestId }: { requestId: string }) => inFlight.delete(requestId);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
// Per test, because some files clear every listener with removeAllListeners().
beforeEach(() => {
  server.events.on('request:start', track);
  server.events.on('request:end', settle);
  server.events.on('request:unhandled', settle);
  server.events.on('unhandledException', settle);
});
afterEach(() => {
  server.events.removeListener('request:start', track);
  server.events.removeListener('request:end', settle);
  server.events.removeListener('request:unhandled', settle);
  server.events.removeListener('unhandledException', settle);
  server.resetHandlers();
  const pending = [...inFlight.values()];
  inFlight.clear();
  if (pending.length > 0) {
    throw new Error(`Request still in flight when the test ended: ${pending.join(', ')}`);
  }
});
afterAll(() => server.close());

// jsdom implements neither of these, and the conversation screen uses both.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
      addListener: () => {},
      removeListener: () => {},
    }) as unknown as MediaQueryList;
}

if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

// jsdom implements no media element at all. Screens are given a fake player;
// this covers the provider tests that exercise the real composition root.
HTMLMediaElement.prototype.play = () => Promise.resolve();
HTMLMediaElement.prototype.pause = () => {};
