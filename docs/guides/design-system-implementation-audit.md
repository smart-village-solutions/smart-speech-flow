# KasselDIALOG design-system implementation audit

Audit date: 2026-11-01. Implementation branch: `codex/consolidate-typography`.
Reference: [published Figma library](https://www.figma.com/design/JsHzcu2sPXrKOx1GKLqfaD/Designsystem-KasselDIALOG?node-id=8-987).
Typography baseline: `fedf07c8`; the keyboard-focus and inheritance corrections are included with this report.

## Assessment

The application already implements 37 of the 40 public UI families as reusable components or feature compositions. The other three are explicitly labelled design proposals in Figma. Publication makes those proposals available to designers; it does not implement their React APIs.

All 114 Figma tokens with CSS syntax were compared with their runtime values: 59 colors and 55 dimensions, each resolved under Light and Dark (228 comparisons). They match within CSSOM color serialization precision; alpha comparisons allow one 8-bit step. The additional proposed essential-muted color has no runtime mapping. Focus adopts the existing published proposal values in this branch.

The 19 shared Figma text styles use reading sizes 12, 14, 16, 18, 24 and 28 px. The 20 px TypingDots value is graphic geometry. Semantic aliases, weights, leading and tracking remain distinct.

## Corrections made during the audit

- Added a 2 px keyboard outline with a 2 px offset. Shared primitives carry `focus-ring`, which also works in Radix portals. Feature controls inside `ScreenShell` receive the same treatment. The native checkbox remains accessible and paints focus on its visible sibling.
- Excluded the outline from focus-time transitions: the previous `transition-all` on Button animated its width from zero, briefly hiding focus.
- Added `--focus-visible`: Light resolves to `#1d538b`, Dark to `#79b8f6`, from Figma's `proposed/focus/visible`. Only controls on the fixed-white header and light legal links override it to Light; the header's themed account dropdown keeps the Dark outline on its dark surface.
- Set the default `ScreenShell` text role to 16 px. Unstyled children previously inherited the legacy body's 18 px.
- Set Inter and the body role explicitly on all four Radix dialog surfaces: ConfirmDialog, QuestionDialog, FeedbackSheet and AdminInviteOverlay. Portals live outside ScreenShell and previously inherited the legacy system font and 18 px default.
- Extended the existing compiled-CSS guard for focus tokens, the outline rule and the checkbox's peer-focus selector.

Figma remains the published reference; this code audit did not edit or republish the library. Its descriptions still identify the focus treatment as a proposal, now adopted locally in this branch.

## Public UI families

“Source component” records implementation ownership, not a claim that every visual state has passed a full product accessibility or pixel comparison.

| Figma family | Code implementation | Relationship |
| --- | --- | --- |
| `KD/Button` | `Button` [ui/primitives/Button.tsx](../../services/frontend/src/ui/primitives/Button.tsx) | Source component |
| `KD/NewSessionAction` | `AdminNewSessionButton` [features/admin/AdminNewSessionButton.tsx](../../services/frontend/src/features/admin/AdminNewSessionButton.tsx) | Source component |
| `KD/CodeInput` | `CodeInput` [ui/patterns/CodeInput.tsx](../../services/frontend/src/ui/patterns/CodeInput.tsx) | Source component |
| `KD/Checkbox` | `Checkbox` [ui/primitives/Checkbox.tsx](../../services/frontend/src/ui/primitives/Checkbox.tsx) | Source component |
| `KD/StatusChip` | No generic equivalent | Design proposal |
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
| `KD/EmptyState` | Inline feature notices only | Design proposal |
| `KD/AppHeader` | `AppHeader` [ui/patterns/AppHeader.tsx](../../services/frontend/src/ui/patterns/AppHeader.tsx) | Source component |
| `KD/CopyLink` | `InviteShareRow` [features/admin/InviteShareRow.tsx](../../services/frontend/src/features/admin/InviteShareRow.tsx) | Source component |
| `KD/Invitation` | `AdminInviteOverlay` [features/admin/AdminInviteOverlay.tsx](../../services/frontend/src/features/admin/AdminInviteOverlay.tsx) | Source component |
| `KD/InlineAlert` | Feature-specific errors and notices only | Design proposal |
| `KD/Textarea` | `Textarea` [ui/primitives/Textarea.tsx](../../services/frontend/src/ui/primitives/Textarea.tsx) | Source component |
| `KD/IntroductionCard` | `AdminDashboardScreen` [features/admin/AdminDashboardScreen.tsx](../../services/frontend/src/features/admin/AdminDashboardScreen.tsx) | Feature composition |

## Assets and private parts

The other 16 public families comprise 12 icon roles and four asset/pattern roles:

| Figma role | Source |
| --- | --- |
| Icon/Feedback, Theme, Home, Account, Microphone, Keyboard, Playback, Close, Star, Arrow, Send, Pause | Existing `lucide-react` usages. Theme and playback select their icon dynamically; arrows mirror under RTL. This audit checks roles and usage, not vector path identity. |
| HeaderLogo | [AppHeader](../../services/frontend/src/ui/patterns/AppHeader.tsx), `/assets/Logo.png`. Its colored, fixed-white header asset is distinct from the monochrome BrandLogo component. |
| LegalLinks | [LegalLinks](../../services/frontend/src/ui/patterns/LegalLinks.tsx), with a fixed-Light tone for white surfaces. |
| SponsorStrip | [StartPageFooter](../../services/frontend/src/ui/patterns/StartPageFooter.tsx), `/assets/Foerdermittelgeber.png` and `/assets/Stadt.png`. |
| FlagAvatar | [FlagAvatar](../../services/frontend/src/ui/patterns/FlagAvatar.tsx), sizes 16 / 22 / 40 / 72 px. Studio-supplied imagery remains dynamic. |

Eight `.KD/*` families are private construction parts and composition examples. They do not require corresponding public React exports.

## API correspondence

- Button.Variant maps to `variant="pill|sheet|compact"`. React children provide label/icon content; callers own action colors.
- Checkbox.Checked maps to native `checked`; State follows focus, hover and `disabled`. It does not need a runtime State prop.
- TextField.Density maps to `density`. ShowLabel maps inversely to `labelHidden`. Filled is derived from the actual value, while `error` supplies the error text and accessible invalid state.
- Textarea.Plain is the primitive; Field is the treatment composed by FeedbackQuestion. Filled and interaction states are derived from content and native input state.
- IconButton's 32 / 36 px sizes map to `tone="close|default"`. ComposerControls owns the specialized 64 px actions. Figma's icon swap maps to React children.
- AppHeader.Layout is derived from breakpoints and the shell's keyboard state. Navigation visibility maps to `showNavigation`; account content is supplied through `trailing`.
- Message and feedback lifecycles come from domain state. Figma prototypes are illustrations, not substitutes for runtime state machines, keyboard behavior or screen-reader announcements.

## Remaining differences and limits

1. **Generic proposals:** StatusChip, EmptyState and InlineAlert have no equivalent shared API. The recovery feature has its own [StatusChip / Chip](../../services/frontend/src/features/recovery/StatusChip.tsx), with request-specific semantics and different tones; it is not the generic four-tone Figma component.
2. **Additional visual states:** some error/disabled/selected skins in Figma remain proposals, especially on Textarea and IconButton. Native disabled behavior exists; that does not imply every proposed skin is implemented.
3. **TextField density and leading:** the published Default and Compact filled masters both measure 67 px high with an 8 px vertical input padding and 4 px label gap. Their labels use 14/21 px and values 16/24 px. [TextField](../../services/frontend/src/ui/primitives/TextField.tsx) intentionally retains 10 / 8 px vertical padding for Default / Compact and a 6 px label gap; leading currently inherits 1.6. The published Figma pair therefore loses the density distinction agreed during consolidation. Preserve that code distinction; reconcile the Figma density geometry and field leading in a dedicated update before claiming pixel parity.
4. **Muted text:** `proposed/text/essential-muted` is not adopted. Existing low-contrast muted/placeholder colors remain; this audit is not a contrast or accessibility release certification.
5. **Mobile targets:** the published 32 / 36 px icon controls and smaller rating controls need a separate hit-area review against the project's intended mobile targets. Their geometry was preserved rather than silently diverging from Figma.
6. **Code Connect:** Button and TextField currently return empty Code Connect maps. Source links and the matrix above exist, but generated connected snippets are not configured.
7. **Legacy and other branding:** NotFoundPage, ToastContext and legacy body defaults are outside the KasselDIALOG ScreenShell migration. The SSF brand retains its own accent and logo treatment. They were not restyled to manufacture whole-repository parity.
8. **Coverage:** six responsive Light/Dark browser cases cover the shared controls, real AdminHeader including its themed account dropdown, default shell typography and ConfirmDialog. Dialog dismissal, native checkbox keyboard toggling and horizontal overflow were checked. Other feature workflows and assistive technologies still require their own validation.

## Validation

The browser reproduction first failed because keyboard focus was absent and portal typography inherited system-ui / 18 px. After the corrections:

- All 228 mapped-token comparisons pass.
- Shared focus is visible immediately at widths 320 / 390 / 800 px in Light and Dark.
- The fixed-white header controls retain the Light outline in Dark mode; the account dropdown uses the Dark outline.
- Default shell and ConfirmDialog text use Inter / 16 px.
- Checkbox Space toggling and dialog Escape dismissal work; tested layouts have no horizontal overflow.
- Final checks pass: `bash scripts/check-tokens.sh`, `npm run build`, `npm run lint`, and all 1,541 tests across 173 frontend test files. The build retains its existing large-chunk warning; the suite retains its baseline asynchronous test/MSW warnings.

The check script is committed. The browser harness was a temporary audit fixture and is removed after verification; it does not add a production route or dependency.
