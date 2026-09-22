## 1. Frontend

- [x] 1.1 Remove the `/admin` password route, `AdminLoginScreen` and
  `useAdminAuth`; `/admin` falls through to the not-found page.
- [x] 1.2 Remove `/customer`, its `ProtectedRoute` and the legacy customer
  modules that nothing else imports.
- [x] 1.3 Remove `VITE_APP_PASSWORD` from the runtime configuration and the
  unused `admin.login` catalogue entries.
- [x] 1.4 Move the admin navigation, theme and session-flow tests from the
  password gate to the tenant login route.

## 2. Gateway and deployment

- [x] 2.1 Remove `X-SSF-Legacy-Access` from the CORS allow-list.
- [x] 2.2 Remove the retired variables from Compose, the Dockerfile and the
  environment examples.
- [x] 2.3 Assert that legacy-header-only admin requests receive 401, also when
  the retired variables are still set.
- [x] 2.4 Assert that no build argument or default embeds the retired password
  in the frontend image.

## 3. Documentation and verification

- [x] 3.1 Update the operator, security, deployment and smoke-test documentation.
- [x] 3.2 Run the frontend gates, the gateway and compose tests, and the
  frontend container build tests.
- [ ] 3.3 After deployment, verify in production that `/admin` returns the
  not-found page, legacy-header-only requests receive 401, `/login` works for
  a user with `ssf-user`, and the QR-code customer flow is unchanged.
