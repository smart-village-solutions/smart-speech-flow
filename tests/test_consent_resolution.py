"""Consent resolution is a pure function of the live mode and the guest answer."""

import pytest

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.consent_resolution import resolve_consent
from tests.runtime_policy_helpers import configuration


@pytest.mark.parametrize("answer", [True, False, None])
def test_disabled_mode_ignores_the_answer(answer):
    status = resolve_consent(configuration(mode="disabled"), answer)
    assert status is ConsentStatus.POLICY_DISABLED


def test_ask_with_affirmative_answer_grants():
    status = resolve_consent(configuration(mode="ask"), True)
    assert status is ConsentStatus.GRANTED


def test_ask_with_negative_answer_declines():
    status = resolve_consent(configuration(mode="ask"), False)
    assert status is ConsentStatus.DECLINED


def test_ask_with_absent_answer_declines():
    status = resolve_consent(configuration(mode="ask"), None)
    assert status is ConsentStatus.DECLINED


@pytest.mark.parametrize("answer", [True, False, None])
def test_failed_read_leaves_pending(answer):
    # `pending`, not `declined`: the guest was never successfully asked, and
    # labelling it `declined` would hide a Studio outage behind a guest choice.
    assert resolve_consent(None, answer) is ConsentStatus.PENDING
