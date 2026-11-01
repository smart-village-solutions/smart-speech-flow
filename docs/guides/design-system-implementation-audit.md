# KasselDIALOG design-system implementation audit

Audit date: 2026-11-01. Implementation branch: `codex/consolidate-typography`.
Reference: [Figma library](https://www.figma.com/design/JsHzcu2sPXrKOx1GKLqfaD/Designsystem-KasselDIALOG?node-id=8-987).

## Assessment

All 40 public UI families now have reusable implementations or explicit feature compositions. StatusChip, InlineAlert and EmptyState are implemented and used in existing features. Figma and the frontend share 129 mapped tokens: 70 colors and 59 dimensions. Their resolved values are exported in [the contract](../../services/frontend/design-system.contract.json) and checked against actual browser styles.

The library contains 64 canonical families: 40 public UI families, 16 public icon/asset families and eight private construction/example families. Three variable collections contain 276 variables. The 21 shared text styles retain six reading sizes: 12, 14, 16, 18, 24 and 28 px. Error and metadata captions have separate semantic roles; the 20 px TypingDots value is graphic geometry.

## Reconciled behavior

- StatusChip supports neutral/success/warning/danger. The recovery adapter preserves its feature API while reusing the shared badge.
- InlineAlert supports optional title/content and native announcement roles. Static notices may override the role. FeedbackError and administration errors reuse it.
- EmptyState supports title, optional description and an action slot. Administration empty views reuse it.
- TextField preserves Default/Compact input heights of 46/42 px, vertical padding of 10/8 px, a 6 px label gap, 14/21 labels and 16/24 values. Invalid borders persist during focus. External help and generated error descriptions coexist.
- Textarea offers plain/field variants, three rows by default, and consistent invalid/disabled/focus treatments. Feedback, recovery and archive fields reuse it.
- IconButton supports 32/36/64 px visual sizes, selection and disabled opacity. Shared icon controls and shorter buttons have at least 44 px hit areas. Rating buttons are 44 px and wrap on narrow screens.
- CodeInput exposes an invalid state, used for rejected access codes. Figma State=Error maps to this prop; Filled remains content-derived.
- Muted, placeholder and link colors are strengthened in both themes. Field/checkbox/code borders share a clearer semantic border. Four-tone notices share foreground, surface and border roles.
- Focus uses a 2 px outline with a 2 px outside offset by default. Clipped account-menu rows override the offset to -4 px so the outline remains visible inside the menu. Fixed-white header controls retain the Light color; the dropdown inherits the active theme. StarRating and ScaleInput carry the shared focus utility directly, so ratings also retain themed focus in Radix portals outside ScreenShell. Browser cases cover portal focus and painted pixels in a single-row account menu.
- ScreenShell and the four Radix dialog surfaces explicitly use Inter and the 16 px body role, including portalled content.

Figma masters, dependent patterns and documentation were updated, including shared feedback examples in both themes. The original Alt-Stand references remain separate.

## Public UI families

“Source component” records implementation ownership, not a claim that every visual state has passed a full product accessibility or pixel comparison.

| Figma family | Code implementation | Relationship |
| --- | --- | --- |
| `KD/Button` | `Button` [ui/primitives/Button.tsx](../../services/frontend/src/ui/primitives/Button.tsx) | Source component |
| `KD/NewSessionAction` | `AdminNewSessionButton` [features/admin/AdminNewSessionButton.tsx](../../services/frontend/src/features/admin/AdminNewSessionButton.tsx) | Source component |
| `KD/CodeInput` | `CodeInput` [ui/patterns/CodeInput.tsx](../../services/frontend/src/ui/patterns/CodeInput.tsx) | Source component |
| `KD/Checkbox` | `Checkbox` [ui/primitives/Checkbox.tsx](../../services/frontend/src/ui/primitives/Checkbox.tsx) | Source component |
| `KD/StatusChip` | `StatusChip` [ui/primitives/StatusChip.tsx](../../services/frontend/src/ui/primitives/StatusChip.tsx) | Shared component |
| `KD/ConversationRow` | `AdminSessionRow` [features/admin/AdminSessionRow.tsx](../../services/frontend/src/features/admin/AdminSessionRow.tsx) | Source component |
| `KD/LanguageOption` | `LanguageSelectScreen` [features/language-select/LanguageSelectScreen.tsx](../../services/frontend/src/features/language-select/LanguageSelectScreen.tsx) | Feature composition |
| `KD/OrganizationLink` | `TenantLoginScreen` [features/login/TenantLoginScreen.tsx](../../services/frontend/src/features/login/TenantLoginScreen.tsx) | Feature composition |
| `KD/AccountMenu` | `AdminUserMenu` [ui/patterns/AdminUserMenu.tsx](../../services/frontend/src/ui/patterns/AdminUserMenu.tsx) | Source component |
| `KD/StarRating` | `StarRating` [ui/patterns/StarRating.tsx](../../services/frontend/src/ui/patterns/StarRating.tsx) | Source component |
| `KD/ScaleInput` | `ScaleInput` [ui/patterns/ScaleInput.tsx](../../services/frontend/src/ui/patterns/ScaleInput.tsx) | Source component |
| `KD/CodeDisplay` | `CodeDisplay` [ui/patterns/CodeDisplay.tsx](../../services/frontend/src/ui/patterns/CodeDisplay.tsx) | Source component |
| `KD/TextField` | `TextField` [ui/primitives/TextField.tsx](../../services/frontend/src/ui/primitives/TextField.tsx) | Source component |
| `KD/IconButton` | `IconButton` [ui/primitives/IconButton.tsx](../../services/frontend/src/ui/primitives/IconButton.tsx) | Source component |
| `KD/Waveform` | `Waveform` [ui/patterns/Waveform.tsx](../../services/frontend/src/ui/patterns/Waveform.tsx) | Source component |
| `KD/TypingDots` | `TypingDots` [ui/patterns/TypingDots.tsx](../../services/frontend/src/ui/patterns/TypingDots.tsx) | Source component |
| `KD/BubblePlayer` | `BubblePlayer` [ui/patterns/BubblePlayer.tsx](../../services/frontend/src/ui/patterns/BubblePlayer.tsx) | Source component |
| `KD/RecordingBubble` | `RecordingBubble` [ui/patterns/RecordingBubble.tsx](../../services/frontend/src/ui/patterns/RecordingBubble.tsx) | Source component |
| `KD/MessageBubble` | `MessageBubble` [ui/patterns/MessageBubble.tsx](../../services/frontend/src/ui/patterns/MessageBubble.tsx) | Source component |
| `KD/ComposerControls` | `ComposerControls` [features/conversation/ComposerControls.tsx](../../services/frontend/src/features/conversation/ComposerControls.tsx) | Source component |
| `KD/ConversationStatus` | `ConversationStatus` [features/conversation/ConversationStatus.tsx](../../services/frontend/src/features/conversation/ConversationStatus.tsx) | Source component |
| `KD/SessionStatus` | `SessionStatusOverlay` [features/admin/SessionStatusOverlay.tsx](../../services/frontend/src/features/admin/SessionStatusOverlay.tsx) | Source component |
| `KD/RecordingBand` | `RecordingBand` [features/recording/RecordingBand.tsx](../../services/frontend/src/features/recording/RecordingBand.tsx) | Source component |
| `KD/SignaturePad` | `SignaturePad` [features/recording/SignaturePad.tsx](../../services/frontend/src/features/recording/SignaturePad.tsx) | Source component |
| `KD/Skeleton` | `FeedbackSkeleton`, `LanguageSkeleton`, `ConsentSkeleton` [features/feedback/FeedbackSkeleton.tsx](../../services/frontend/src/features/feedback/FeedbackSkeleton.tsx) | Three source components |
| `KD/FeedbackError` | `FeedbackError` [features/feedback/FeedbackError.tsx](../../services/frontend/src/features/feedback/FeedbackError.tsx) | Source component |
| `KD/FeedbackThanks` | `FeedbackThanks` [features/feedback/FeedbackThanks.tsx](../../services/frontend/src/features/feedback/FeedbackThanks.tsx) | Source component |
| `KD/FeedbackQuestion` | `FeedbackQuestion` [features/feedback/FeedbackQuestion.tsx](../../services/frontend/src/features/feedback/FeedbackQuestion.tsx) | Source component |
| `KD/FeedbackSheet` | `FeedbackSheet` [features/feedback/FeedbackSheet.tsx](../../services/frontend/src/features/feedback/FeedbackSheet.tsx) | Source component |
| `KD/ConfirmDialog` | `ConfirmDialog` [ui/patterns/ConfirmDialog.tsx](../../services/frontend/src/ui/patterns/ConfirmDialog.tsx) | Source component |
| `KD/QuestionDialog` | `QuestionDialog` [ui/patterns/QuestionDialog.tsx](../../services/frontend/src/ui/patterns/QuestionDialog.tsx) | Source component |
| `KD/SystemLoadCard` | `SystemLoadCard` [features/admin/SystemLoadCard.tsx](../../services/frontend/src/features/admin/SystemLoadCard.tsx) | Source component |
| `KD/ConversationHistory` | `AdminSessionList` [features/admin/AdminSessionList.tsx](../../services/frontend/src/features/admin/AdminSessionList.tsx) | Source component |
| `KD/EmptyState` | `EmptyState` [ui/patterns/EmptyState.tsx](../../services/frontend/src/ui/patterns/EmptyState.tsx) | Shared component |
| `KD/AppHeader` | `AppHeader` [ui/patterns/AppHeader.tsx](../../services/frontend/src/ui/patterns/AppHeader.tsx) | Source component |
| `KD/CopyLink` | `InviteShareRow` [features/admin/InviteShareRow.tsx](../../services/frontend/src/features/admin/InviteShareRow.tsx) | Source component |
| `KD/Invitation` | `AdminInviteOverlay` [features/admin/AdminInviteOverlay.tsx](../../services/frontend/src/features/admin/AdminInviteOverlay.tsx) | Source component |
| `KD/InlineAlert` | `InlineAlert` [ui/patterns/InlineAlert.tsx](../../services/frontend/src/ui/patterns/InlineAlert.tsx) | Shared component |
| `KD/Textarea` | `Textarea` [ui/primitives/Textarea.tsx](../../services/frontend/src/ui/primitives/Textarea.tsx) | Source component |
| `KD/IntroductionCard` | `AdminDashboardScreen` [features/admin/AdminDashboardScreen.tsx](../../services/frontend/src/features/admin/AdminDashboardScreen.tsx) | Feature composition |


## Assets and private parts

The other 16 public families cover 12 icon roles (Feedback, Theme, Home, Account, Microphone, Keyboard, Playback, Close, Star, Arrow, Send, Pause), HeaderLogo, LegalLinks, SponsorStrip and FlagAvatar. Existing assets and lucide-react usages remain their source. HeaderLogo and SponsorStrip keep white contexts; QR/signature keep invariant color pairs.

Eight `.KD/*` families remain private construction parts and examples, without corresponding public React exports.

## API correspondence

- Button.Variant maps to `variant="pill|sheet|compact"`; React children supply label/icon content.
- Checkbox.Checked maps to native checked; State follows focus, hover and disabled.
- TextField.Density maps to density. ShowLabel maps inversely to labelHidden. Filled derives from value. The error prop supplies generated error text and invalid semantics; native aria-invalid also works.
- Textarea.Variant maps to `variant="plain|field"`. Native content, aria-invalid and disabled determine state.
- IconButton.Size maps to `size="small|medium|large"`; the existing tone API stays compatible. Selection uses aria-pressed.
- StatusChip.Tone and InlineAlert.Tone map to lowercase tone props. InlineAlert and EmptyState optional actions use normal React slots; Figma uses instance-swap properties.
- Ratings remain button groups with aria-pressed inside fieldsets. ScaleInput labels are optional.
- AppHeader.Layout follows breakpoints and keyboard state. Message and feedback lifecycles remain domain-driven.

## Repeatable validation

From `services/frontend`:

```sh
npm ci
npx playwright install chromium
npm run dev
# Open /design-system.html?theme=dark&dir=rtl
npm run test:design-system
npm test
npm run build
npm run lint
npm run fallow:audit -- --changed-since origin/main
bash scripts/check-tokens.sh
```

The gallery uses real components/providers and the Kassel brand DOM attribute. It is a development HTML entry, not a production route. Twelve browser cases cover Light/Dark at 320/390/800 px in LTR/RTL: keyboard behavior, focus/invalid/disabled states, field geometry, hit areas, ratings, dialog dismissal and horizontal overflow. Two cases compare every mapped token against the Figma contract; two verify visible focus pixels in a single-row account menu. `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` optionally selects an installed browser.

Current checks after incorporating main: 1,610 unit/component tests across 177 files, 16 browser cases, build, lint, Fallow's CI gate and compiled-CSS checks. Browser checks include alpha-composited contrast for muted/placeholder and notice text, field borders, fixed-white header versus themed dropdown focus, visible menu focus pixels and portalled ratings. The Figma integrity audit reports zero alias, binding, instance, matrix, prototype, font, placeholder, duplicate-family, documentation-overflow or token-parity issues. The existing large-chunk warning and baseline asynchronous/MSW test warnings remain.

## Publication and limits

The user published the reconciliation update. A subsequent read-only Figma check confirmed `CURRENT` publication status for all 56 public families (40 UI and 16 icon/asset families) and all three variable collections. Consuming files can now adopt the published update.

Button and TextField Code Connect maps remain empty. Source references and this matrix exist; connected snippets are not configured. Older pinned source URLs describe the original baseline; this branch and the contract describe the reconciliation.

These checks establish shared-component/token agreement, not every product workflow or screen-reader combination. Legacy NotFoundPage/ToastContext and SSF-specific branding remain separate from the KasselDIALOG migration.
