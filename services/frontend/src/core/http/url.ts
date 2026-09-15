/** A url that already names its own origin, or its own scheme. */
const ABSOLUTE = /^([a-z][a-z\d+\-.]*:|\/\/)/i;

/**
 * Puts a gateway path on the gateway's origin.
 *
 * The deployed SPA and the gateway are on different hosts —
 * `translate.smart-village.solutions` and `ssf.smart-village.solutions`. Axios
 * applies its own `baseURL`; resolving here also gives live and historical
 * messages one stable cache key in the authenticated audio loader.
 *
 * In development `apiBaseUrl` is empty, because the dev server proxies `/api`.
 */
export function resolveApiUrl(apiBaseUrl: string, url: string): string {
  if (url === '' || apiBaseUrl === '' || ABSOLUTE.test(url)) {
    return url;
  }

  const base = apiBaseUrl.replace(/\/$/, '');
  return url.startsWith('/') ? `${base}${url}` : `${base}/${url}`;
}
