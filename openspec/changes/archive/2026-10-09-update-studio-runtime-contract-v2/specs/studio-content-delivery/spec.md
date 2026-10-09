## ADDED Requirements

### Requirement: Cached Studio content

SSF SHALL cache Studio content, sanitised, keyed by tenant and
`configurationRevision`, and SHALL refresh it from every live read. Display
requests SHALL use content no older than the configured cache period, default
60 seconds, then make one live read shared by concurrent requests. When that
read fails, SSF SHALL serve the last known content. The cache SHALL NOT hold
the storage mode.

#### Scenario: Studio outage during display

- **WHEN** a display request needs fresh content and Studio is unavailable
- **THEN** SSF serves the last known content for that tenant

#### Scenario: Revision changes

- **WHEN** a live read returns a new `configurationRevision`
- **THEN** later display requests receive the new content

### Requirement: Installation content route

SSF SHALL serve `GET /api/content/installation` without authentication. It
SHALL return the installation logo and icon, the imprint, privacy policy and
accessibility statement URLs, the start page and login texts and the
installation feedback form, with `Cache-Control: public, max-age=60` and the
revision as ETag.

#### Scenario: Conditional request

- **WHEN** a request carries `If-None-Match` equal to the current revision
- **THEN** SSF answers 304

#### Scenario: No content held

- **WHEN** installation content has never been read successfully
- **THEN** SSF answers 503 and the browser uses bundled copy

### Requirement: Guest content routes

SSF SHALL serve `GET /api/customer/session/{session_id}/languages` and
`GET /api/customer/session/{session_id}/content/{language}` to holders of the
session key, including within the feedback grace period after the session
ends. The language list SHALL contain SSF's guest languages; entries Studio
provides SHALL carry Studio's native name and icon. The content route SHALL
return the live storage mode, or `unknown` when it cannot be read, and either
Studio's guest texts and feedback form for that language or `provided: false`.

#### Scenario: Language provided by Studio

- **WHEN** the guest requests content for `en` and Studio provides `en`
- **THEN** the response carries Studio's explanation, storage question and
  feedback form

#### Scenario: Language not provided by Studio

- **WHEN** the guest requests content for `ar` and Studio does not provide it
- **THEN** the response carries `provided: false` and the live storage mode

#### Scenario: Locale mapping

- **WHEN** Studio provides the locale `kmr`
- **THEN** SSF offers it as its language `ku`
- **AND THEN** a Studio locale SSF does not support is skipped

### Requirement: Staff content route

SSF SHALL serve `GET /api/admin/content` to authenticated staff, resolving the
tenant from the token. It SHALL return the staff texts, the staff feedback
form, the tenant logo and icon, the tenant time zone and staff-language names
for the guest languages Studio provides.

#### Scenario: Authenticated staff member

- **WHEN** a staff member of `tenant-kassel` requests staff content
- **THEN** SSF returns `tenant-kassel`'s staff content

#### Scenario: No token

- **WHEN** the request carries no valid token
- **THEN** SSF answers 401

### Requirement: Hybrid guest languages

SSF SHALL keep its own guest language list. For a guest language Studio
provides, every guest-facing text Studio defines SHALL come from Studio; for a
guest language Studio does not provide, the bundled texts SHALL be used
unchanged. The staff language SHALL NOT be offered to guests.

#### Scenario: Partial Studio coverage

- **WHEN** Studio provides only English
- **THEN** guests choosing English see Studio texts
- **AND THEN** guests choosing any other SSF language see the bundled texts

### Requirement: Safe rendering of Studio markup

SSF SHALL sanitise Studio HTML with an allowlist before serving it. The browser
SHALL render it by rebuilding allowlisted elements and SHALL NOT write raw HTML
into the page. Links SHALL be limited to `https:` and `mailto:` and open in a
new tab. Empty blocks SHALL be dropped.

#### Scenario: Script in Studio content

- **WHEN** Studio content contains a `script` element or an `on*` attribute
- **THEN** neither reaches the rendered page

### Requirement: Bundled fallback for Studio content

The browser SHALL show bundled copy for any field whose Studio content is
missing, invalid or not yet loaded, except on the consent screen, which SHALL
wait for guest content up to the request timeout before falling back.

#### Scenario: Content route fails

- **WHEN** the staff content route fails
- **THEN** the dashboard shows its bundled texts

### Requirement: Legal links on every page

Every page SHALL link to the imprint, the privacy policy and, when provided,
the accessibility statement. On conversation screens the links SHALL sit in a
row below the microphone row.

#### Scenario: Conversation screen

- **WHEN** a guest is on the conversation screen
- **THEN** the legal links are visible below the microphone row

#### Scenario: Accessibility statement absent

- **WHEN** neither installation content nor the installation's bundled fallback
  has an accessibility statement URL
- **THEN** that link is omitted

#### Scenario: Invalid legal URL from Studio

- **WHEN** installation content has no valid URL for a legal link and the
  bundled fallback has one
- **THEN** the bundled URL is linked

### Requirement: Tenant display name is not shown

SSF SHALL NOT display the tenant display name from the runtime configuration on
any page. The staff login organisation chooser SHALL keep using the login
directory's display names.

#### Scenario: Staff dashboard

- **WHEN** a staff member opens the dashboard
- **THEN** no tenant display name from the runtime configuration is shown
