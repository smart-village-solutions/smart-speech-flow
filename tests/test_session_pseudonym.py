"""Session references stored in telemetry must not be reversible.

Session ids are 32-bit. The four `sha256(session_id)[:12]` helpers in the
gateway are log hygiene, not pseudonymisation: a 32-bit input space is
exhaustible in milliseconds, so an unkeyed digest is a reversible encoding of
the id it was meant to hide. Anything written to a 30-day store has to be keyed.
"""

import hashlib
import re

import pytest

from services.api_gateway.session_pseudonym import (
    MISSING_REFERENCE,
    SESSION_KEY_ENV,
    SessionPseudonymizer,
    session_ref,
)

OPAQUE_REF = re.compile(r"\A[0-9a-f]{16,64}\Z")


class TestShape:
    def test_a_reference_matches_the_opaque_ref_attribute_shape(self):
        assert OPAQUE_REF.match(SessionPseudonymizer(key=b"k").reference("42"))

    def test_the_same_id_and_key_always_give_the_same_reference(self):
        pseudonymizer = SessionPseudonymizer(key=b"deployment-secret")

        first = pseudonymizer.reference("42")
        second = pseudonymizer.reference("42")

        assert first == second

    def test_different_ids_give_different_references(self):
        pseudonymizer = SessionPseudonymizer(key=b"deployment-secret")

        assert pseudonymizer.reference("42") != pseudonymizer.reference("43")


class TestIrreversibility:
    def test_the_reference_is_not_the_unkeyed_digest_the_logs_use(self):
        # If it were, telemetry would inherit exactly the weakness it exists to
        # avoid -- and would also join telemetry rows to log lines.
        unkeyed = hashlib.sha256(b"42").hexdigest()

        assert not unkeyed.startswith(SessionPseudonymizer(key=b"k").reference("42"))

    def test_a_different_key_gives_a_different_reference_for_the_same_id(self):
        # This is the whole point: without the key the id space cannot be
        # enumerated, however small it is.
        assert SessionPseudonymizer(key=b"key-a").reference(
            "42"
        ) != SessionPseudonymizer(key=b"key-b").reference("42")

    def test_brute_forcing_the_whole_plausible_id_space_finds_no_match(self):
        target = SessionPseudonymizer(key=b"the-deployment-secret").reference("4242")
        attacker = SessionPseudonymizer(key=b"")

        assert all(attacker.reference(str(n)) != target for n in range(20000))


class TestMissingInput:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_a_missing_session_id_is_a_constant_not_a_hash_of_nothing(self, value):
        # A hash of the empty string is a stable reference that would group
        # every session-less event as if it were one session.
        assert SessionPseudonymizer(key=b"k").reference(value) == MISSING_REFERENCE

    def test_the_missing_sentinel_still_matches_the_stored_attribute_shape(self):
        # It travels through the same allowlist as a real reference, so a
        # sentinel of a different shape would be rejected at the wire.
        assert OPAQUE_REF.match(MISSING_REFERENCE)

    def test_the_missing_sentinel_cannot_be_mistaken_for_a_real_reference(self):
        pseudonymizer = SessionPseudonymizer(key=b"k")

        assert all(
            pseudonymizer.reference(str(n)) != MISSING_REFERENCE for n in range(5000)
        )


class TestKeyResolution:
    def test_the_key_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv(SESSION_KEY_ENV, "from-the-environment")

        assert SessionPseudonymizer.from_environment().reference(
            "42"
        ) == SessionPseudonymizer(key=b"from-the-environment").reference("42")

    def test_an_unset_key_still_produces_a_reference(self, monkeypatch):
        monkeypatch.delenv(SESSION_KEY_ENV, raising=False)

        assert OPAQUE_REF.match(SessionPseudonymizer.from_environment().reference("42"))

    def test_an_unset_key_is_random_per_process_not_a_shared_default(self, monkeypatch):
        # A hardcoded fallback key is a published key: it would be in the
        # repository, so it would pseudonymise nothing.
        monkeypatch.delenv(SESSION_KEY_ENV, raising=False)

        # Two separate instances: each generates its own key, which is the
        # whole point -- textually alike, semantically unrelated.
        one_process = SessionPseudonymizer.from_environment()
        another_process = SessionPseudonymizer.from_environment()

        assert one_process.reference("42") != another_process.reference("42")

    def test_an_unset_key_is_reported(self, monkeypatch, caplog):
        monkeypatch.delenv(SESSION_KEY_ENV, raising=False)

        with caplog.at_level("WARNING"):
            SessionPseudonymizer.from_environment()

        assert SESSION_KEY_ENV in caplog.text

    def test_a_blank_key_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(SESSION_KEY_ENV, "   ")

        one_process = SessionPseudonymizer.from_environment()
        another_process = SessionPseudonymizer.from_environment()

        assert one_process.reference("42") != another_process.reference("42")


class TestModuleLevelHelper:
    def test_the_helper_is_stable_within_a_process(self):
        first = session_ref("42")
        second = session_ref("42")

        assert first == second

    def test_the_helper_never_raises_on_hostile_input(self):
        for value in (None, "", 42, object()):
            assert isinstance(session_ref(value), str)
