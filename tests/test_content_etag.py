"""The installation ETag follows the body the gateway sends, not only Studio's revision."""

from __future__ import annotations

from services.api_gateway.content_responses import installation_etag, installation_response
from services.api_gateway.studio_v2 import parse_installation_content_v2
from services.studio_mock import contract_fixtures


def body():
    return installation_response(
        parse_installation_content_v2(contract_fixtures.installation_content_v2(None))
    )


def test_the_tag_names_the_revision_and_is_stable() -> None:
    first, second = body(), body()

    assert installation_etag(first) == installation_etag(second)
    assert installation_etag(first).startswith(f'"{first.revision}.')
    assert installation_etag(first).endswith('"')


def test_the_same_revision_with_another_body_gets_another_tag() -> None:
    before = body()
    after = before.model_copy(
        update={"login": before.login.model_copy(update={"description_html": "<p>x</p>"})}
    )

    assert after.revision == before.revision
    assert installation_etag(after) != installation_etag(before)
