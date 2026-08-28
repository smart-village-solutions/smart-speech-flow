#!/usr/bin/env bash
# Asserts that both the new design tokens and the legacy Tailwind v3 custom
# theme values survive the v4 migration and reach the built CSS.
#
# Needles are written in the form the toolchain emits. Lightning CSS normalises
# colours on the way out, independently of minification, so two of the legacy
# values arrive shortened:
#   --color-text  #333333                  -> #333
#   --shadow-card 0 4px 16px rgb(0 0 0/.08) -> 0 4px 16px #00000014   (.08*255=20=0x14)
# Whitespace is normalised on both sides because the bundle is minified.
set -euo pipefail

cd "$(dirname "$0")/.."

fail() { echo "FAIL: $*" >&2; exit 1; }

rm -rf dist

# The locally installed binary, not `npx`: npx will fetch a package from the
# registry and run its lifecycle scripts when the name is not already present,
# which is not something a verification script should be able to do.
build_log=$(mktemp)
trap 'rm -f "$build_log"' EXIT

./node_modules/.bin/vite build > "$build_log" 2>&1 || {
  cat "$build_log" >&2
  fail "vite build did not succeed"
}

css=$(cat dist/assets/*.css | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

assert() {
  local expected="$1"
  local needle
  needle=$(printf '%s' "$expected" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  case "$css" in
    *"$needle"*) ;;
    *) fail "missing from built CSS: $expected" ;;
  esac
}

# Legacy v3 theme values the untouched pages depend on.
assert '--color-primary: #00a99d'
assert '--color-primary-dark: #0a2342'
assert '--color-background: #f8f8f8'
assert '--color-text: #333'
assert '--radius-card: 12px'
assert '--radius-card-lg: 16px'
assert '--shadow-card: 0 4px 16px #00000014'
assert '--leading-relaxed: 1.6'
assert '--text-base: 18px'

# body belongs to the legacy pages. Asserting the token definitions alone was
# not enough: on 2026-08-25 body was pointing at the new UI's --fg-strong, which
# rendered /admin as white text on white cards while every assertion above still
# passed. The body rule is isolated first, because a bare needle like
# "color:var(--color-text)" also matches the .text-text utility and so passes
# whatever body actually says.
body_rule=$(grep -ohE '(^|\})body\{[^}]*\}' dist/assets/*.css | head -1 | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
[[ -n "$body_rule" ]] || fail "no body rule found in built CSS"

assert_body() {
  local expected="$1"
  case "$body_rule" in
    *"$expected"*) ;;
    *) fail "body must declare $expected, but is: $body_rule" ;;
  esac
}

assert_body 'background:var(--color-background)'
assert_body ';color:var(--color-text)'
assert_body 'font-family:var(--font-legacy)'
assert '--font-legacy: system-ui'

# The new UI paints itself, so nothing of its theme reaches body.
assert '[data-screen-shell]{color-scheme:light}'
assert '.dark [data-screen-shell]{color-scheme:dark}'
assert 'html:has([data-screen-shell]){background:var(--surface-page)}'

# New design tokens, light and dark.
assert '--surface-page: #f4f4f5'
assert '--surface-page: #202020'
assert '--surface-card: #2a2a2a'
assert '--ac: #06b6d4'
assert '--ac: #2464a5'

# Admin tokens. The lamp colours are asserted once, not per theme, because they
# are deliberately theme-independent.
assert '--status-ok: #22c55e'
assert '--status-warn: #f59e0b'
assert '--status-down: #ef4444'
assert '--color-kc-brand: #0d4a73'

# Phase 2 tokens. The QR plate and ink are asserted once rather than per theme,
# because a dark-on-dark QR does not scan and they deliberately have no .dark
# override. Lightning CSS shortens both to three digits on the way out, the same
# normalisation the header of this script documents for --color-text.
assert '--qr-plate: #fff'
assert '--qr-ink: #111'
assert '--spacing-code-lg: 64px'
assert '--spacing-flag-row: 22px'
assert '--container-invite: 500px'
assert '--container-dialog: 400px'
assert '--text-code-lg: 28px'
assert '--text-overlay-title: 22px'

# Phase 3 tokens.
assert '--spacing-admin-content: 128px'
assert '--spacing-status-top: 80px'
assert '--spacing-composer-lift: 40px'
assert '--spacing-flag-pill: 16px'

# The Keycloak imitation stays light in both themes. Asserted because the failure
# is invisible in the light theme: without these pins, dark mode paints
# --fg-strong (#fff) onto the card's white and the fields become unreadable.
assert '.kc-page'
assert '--fg-strong: #111827'
assert '--surface-field: #fff'
assert '--border-card: #d1d5db'

# Tailwind v4 dropped v3's preflight `button { cursor: pointer }`, so every
# button in the app fell back to the browser default arrow. The needle is the
# selector, not `cursor:pointer` on its own: that string already appears in the
# bundle from a `cursor-pointer` utility elsewhere and would match with the base
# rule gone.
assert 'button:not(:disabled)'

# The waveform has no idle track. It draws itself as the clip plays and stays
# solid once heard, so an unplayed message shows an empty row — the export gets
# that by painting unplayed bars the card's own colour in each theme, and this
# says it plainly instead. Asserted because a grey track is the obvious thing to
# reach for and looks deliberate: it was added on 2026-08-27 to fix an invisible
# waveform, and the real fault was the bar width, not the colour.
assert '--surface-wave-idle: transparent'

wave_overrides=$(grep -oE '\-\-surface-wave-idle:[^;}]*' dist/assets/*.css | wc -l)
[[ "$wave_overrides" -eq 1 ]] ||
  fail "--surface-wave-idle is declared $wave_overrides times; the waveform has one colour in both themes"

# The bars are all flex-1, so they add nothing to a bubble sized by its content:
# without a width on the bubble the row collapses to its 49 gaps and every bar
# is drawn zero pixels wide.
#
# This pair covers the token going missing, not the component dropping the
# class: Tailwind scans the test files too, so `.w-bubble-span` is emitted from
# MessageBubble.test.tsx whatever the component says. The component's own use of
# it is held by that test instead — the two guards cover different halves and
# neither is sufficient alone.
assert '--container-bubble-span: calc(100% - var(--spacing-bubble-gutter) - var(--spacing-bubble-inset))'
assert '.w-bubble-span{width:var(--container-bubble-span)}'

echo "PASS: tokens present in built CSS"
