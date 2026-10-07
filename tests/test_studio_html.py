"""The allowlist every Studio HTML fragment passes before it reaches a browser."""

from __future__ import annotations

import pytest

from services.api_gateway.studio_html import safe_html


def test_allowed_markup_survives_and_links_gain_rel() -> None:
    fragment = '<p><strong>German</strong> <a href="https://example.org">link</a></p>'

    assert safe_html(fragment) == (
        '<p><strong>German</strong> <a href="https://example.org" '
        'rel="noopener noreferrer">link</a></p>'
    )


def test_event_handlers_scripts_and_javascript_urls_are_removed() -> None:
    fragment = (
        '<p onclick="evil()"><strong>German</strong> '
        '<a href="https://example.org" onclick="evil()">link</a>'
        '<a href="javascript:evil()">unsafe</a><script>evil()</script></p>'
    )

    cleaned = safe_html(fragment)

    assert "<strong>German</strong>" in cleaned
    assert 'href="https://example.org"' in cleaned
    assert "javascript:" not in cleaned
    assert "onclick" not in cleaned
    assert "<script" not in cleaned
    assert "evil()" not in cleaned


@pytest.mark.parametrize("tag", ["img", "iframe", "style", "div", "span", "h1"])
def test_tags_outside_the_allowlist_are_dropped(tag: str) -> None:
    assert f"<{tag}" not in safe_html(f"<p>a<{tag}>b</{tag}></p>")


def test_mailto_links_are_kept() -> None:
    assert 'href="mailto:a@example.org"' in safe_html('<a href="mailto:a@example.org">a</a>')


def test_unsafe_only_html_never_becomes_empty_text() -> None:
    assert safe_html("<script>unsafe()</script>") == "&lt;script&gt;unsafe()&lt;/script&gt;"


def test_escaped_markup_stays_text() -> None:
    assert safe_html("<p>&lt;img src=x onerror=evil()&gt;</p>") == (
        "<p>&lt;img src=x onerror=evil()&gt;</p>"
    )
