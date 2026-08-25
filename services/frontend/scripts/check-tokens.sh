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
npx vite build > /tmp/ssf-css-build.log 2>&1 || {
  cat /tmp/ssf-css-build.log >&2
  fail "vite build did not succeed"
}

css=$(cat dist/assets/*.css | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')

assert() {
  local needle
  needle=$(printf '%s' "$1" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  case "$css" in
    *"$needle"*) ;;
    *) fail "missing from built CSS: $1" ;;
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
[ -n "$body_rule" ] || fail "no body rule found in built CSS"

assert_body() {
  case "$body_rule" in
    *"$1"*) ;;
    *) fail "body must declare $1, but is: $body_rule" ;;
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

echo "PASS: tokens present in built CSS"
