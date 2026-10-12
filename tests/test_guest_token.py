"""The guest token: issued once, stored as a digest, compared in constant time."""

from services.api_gateway.guest_token import guest_token_admits, issue_guest_token
from services.api_gateway.session_models import Session

REVISION = f"sha256:{'a' * 64}"


def test_the_digest_is_not_the_token_and_admits_only_it() -> None:
    token, digest = issue_guest_token()
    other, _ = issue_guest_token()

    assert token != digest and token not in digest
    assert len(token) >= 43
    assert guest_token_admits(digest, token)
    assert not guest_token_admits(digest, other)
    assert not guest_token_admits(digest, None)
    assert not guest_token_admits(digest, "")


def test_an_unclaimed_session_admits_anyone() -> None:
    assert guest_token_admits(None, None)
    assert guest_token_admits(None, "anything")


def test_the_digest_survives_a_store_round_trip_and_never_goes_public() -> None:
    _, digest = issue_guest_token()
    session = Session(
        id="ABC12345",
        tenant_id="tenant-a",
        configuration_revision=REVISION,
        guest_token_hash=digest,
    )

    restored = Session.from_dict(session.to_dict(include_messages=True))

    assert restored.guest_token_hash == digest
    assert "guest_token_hash" not in session.to_public_dict()


def test_a_record_stored_before_the_field_existed_loads_unclaimed() -> None:
    stored = Session(id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION).to_dict(
        include_messages=True
    )
    stored.pop("guest_token_hash")

    assert Session.from_dict(stored).guest_token_hash is None
