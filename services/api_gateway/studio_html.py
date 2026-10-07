"""The one allowlist for Studio HTML, applied before Studio markup reaches a browser."""

from __future__ import annotations

import html

import nh3

# Passed to nh3 as they are; never mutated.
_TAGS = {"p", "br", "strong", "em", "ul", "ol", "li", "a"}
_ATTRIBUTES = {"a": {"href"}}
_URL_SCHEMES = {"http", "https", "mailto"}
_CONTENT_DROPPED_TAGS = {"script", "style"}


def safe_html(fragment: str) -> str:
    """Keep allowlisted markup; a fragment that cleans to nothing is shown as text."""
    cleaned = nh3.clean(
        fragment,
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        url_schemes=_URL_SCHEMES,
        clean_content_tags=_CONTENT_DROPPED_TAGS,
    )
    return cleaned if cleaned.strip() else html.escape(fragment)
