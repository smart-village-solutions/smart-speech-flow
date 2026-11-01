# Design-system reconciliation implementation plan

**Goal:** Reconcile the existing KasselDIALOG library and frontend on `codex/consolidate-typography`.

**Scope:** Existing public UI roles, shared controls, semantic tokens and their consumers. Preserve business flows, existing public APIs and the six reading sizes. This is an implementation/design reconciliation rather than a new product capability.

## Acceptance checklist

- [x] Implement StatusChip, InlineAlert and EmptyState with accessible semantics and use them in existing features.
- [x] Preserve the recovery-specific StatusChip adapter while reusing the shared badge.
- [x] Align TextField Default/Compact spacing and 14/21 label, 16/24 value typography in code and Figma.
- [x] Reuse one Textarea primitive for plain/field presentations; make native invalid/disabled states consistent.
- [x] Reconcile Button/IconButton selection, focus and disabled states; retain specialized composer colors.
- [x] Adopt readable muted/link/placeholder colors and clear control borders in both themes; retain invariant white header/QR/signature contexts.
- [x] Update the existing Figma masters in place, including tokens, text styles, dependent patterns and documentation.
- [x] Add a development-only component gallery and repeatable browser checks for geometry, states, themes, RTL and token parity.
- [x] Verify all 40 public UI families are source-backed or deliberately composed, with no stale proposal claims for implemented roles.
- [x] Run component tests, full frontend tests, build, lint, compiled-CSS checks, browser checks and independent review.
- [x] Record the final Figma publication state honestly. The connector cannot publish library updates; do not claim they are published.

## Execution

1. Test the missing shared roles, implement them, and replace matching feature markup.
2. Reconcile shared control styles and semantic colors. Verify existing behaviors and responsive layout.
3. Update Figma tokens and masters using the same values; rebuild affected examples and usage notes.
4. Export the mapped token contract, verify it against the running gallery, and inspect Figma and browser previews.
5. Rewrite the implementation audit around the final state, obtain review, commit, and report remaining publication steps.

## Verified outcome

All 40 public UI roles are source-backed or explicitly composed. The final Figma audit reports zero alias, binding, instance, matrix, prototype, font, placeholder, duplicate-family, documentation-overflow or mapped-token parity issues. The library has 64 families, 276 variables, 21 text styles and two effect styles.

Verification passed: 1,554 unit/component tests in 175 files, 14 browser cases, build, lint, compiled-CSS checks and independent review. Browser checks include alpha-composited text/control contrast and the fixed-white header versus themed dropdown focus. Core Figma controls and the responsive browser gallery were visually inspected.

The updated Figma working file still requires manual library publication. Code Connect snippets remain unconfigured; neither limitation blocks use of the local source components or local library masters.
