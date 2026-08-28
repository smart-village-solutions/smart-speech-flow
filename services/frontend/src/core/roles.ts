/**
 * Which end of a session is acting. The gateway validates the language
 * direction against it — customer sends `customer_language → admin_language`,
 * admin the reverse — and answers a mismatch with a 400, so this is never
 * defaulted anywhere. See `api_gateway/routes/session.py:119`.
 */
export type ClientRole = 'admin' | 'customer';
