"""The event contract must be typed, allowlisted, and closed to content."""

import inspect
import re
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

import services.api_gateway.quality_telemetry as contract
import services.api_gateway.quality_telemetry_otlp as adapter
from services.api_gateway.quality_telemetry import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ATTRIBUTE_KEYS,
    SCHEMA_VERSION,
    AttributeKind,
    DisallowedTelemetryAttribute,
    QualityProbeEvent,
    TelemetryMode,
    enforce_allowlist,
    to_otlp_attributes,
)

# Annotations that would let the pipeline's debug_info -- source text,
# transcripts, raw errors -- reach a telemetry emitter.
_UNBOUNDED = re.compile(r"\b(Any|object|dict|Dict|Mapping)\b(?!\[)")
_MAPPINGS = re.compile(r"\b(?:dict|Dict|Mapping)\[([^\[\]]*)\]")


def _event() -> QualityProbeEvent:
    return QualityProbeEvent(
        event_id=uuid4(),
        schema_version=SCHEMA_VERSION,
        emitted_at_utc=datetime.now(timezone.utc),
        event_type="telemetry_probe",
    )


def _offending_parameters(namespace: Mapping[str, Any], defined_in: str) -> list[str]:
    """Parameters whose annotation admits values the allowlist cannot police.

    Anything mapping-shaped must be `[str, str]`: the two allowlisted attribute
    keys and nothing structured. A bare dict, Any, or object is a hole.

    `defined_in` keeps imported third-party symbols out of the walk -- the
    adapter imports the OTel SDK, whose signatures are not ours to police.
    """
    offenders = []
    for owner, function in _functions(namespace, defined_in):
        for name, parameter in inspect.signature(function).parameters.items():
            if name in ("self", "cls") or parameter.annotation is parameter.empty:
                continue
            annotation = str(parameter.annotation)
            bad = bool(_UNBOUNDED.search(annotation)) or any(
                [key.strip() for key in inner.split(",")] != ["str", "str"]
                for inner in _MAPPINGS.findall(annotation)
            )
            if bad:
                offenders.append(f"{owner}({name}: {annotation})")
    return offenders


def _functions(namespace: Mapping[str, Any], defined_in: str):
    for name, value in namespace.items():
        if name.startswith("__") or getattr(value, "__module__", None) != defined_in:
            continue
        if inspect.isfunction(value):
            yield name, value
        elif inspect.isclass(value):
            for method_name, method in vars(value).items():
                if inspect.isfunction(method):
                    yield f"{name}.{method_name}", method


def test_the_acl_check_rejects_a_pipeline_shaped_signature() -> None:
    """Proves the guard below can fail. Without this it is decoration."""

    class Hostile:
        def emit(self, debug_info: "dict[str, Any]") -> None:
            pass

    def leak(payload: "Mapping[str, Any]") -> None:
        pass

    def untyped(payload: "dict") -> None:
        pass

    offenders = _offending_parameters(
        {"Hostile": Hostile, "leak": leak, "untyped": untyped}, __name__
    )

    assert sorted(o.split("(")[0] for o in offenders) == [
        "Hostile.emit",
        "leak",
        "untyped",
    ]


def test_the_acl_check_accepts_the_shipped_contract() -> None:
    def export(name: str, attributes: "Mapping[str, str]", at: datetime) -> None:
        pass

    assert _offending_parameters({"export": export}, __name__) == []


@pytest.mark.parametrize("module", [contract, adapter], ids=["contract", "adapter"])
def test_no_telemetry_entry_point_accepts_an_unbounded_mapping(module) -> None:
    """The ACL: pipeline structures must never be passable into telemetry."""
    assert _offending_parameters(vars(module), module.__name__) == []


def test_event_is_immutable() -> None:
    event = _event()
    with pytest.raises(FrozenInstanceError):
        event.event_type = "mutated"  # type: ignore[misc]


def test_event_rejects_naive_timestamp() -> None:
    event_id, naive = uuid4(), datetime(2026, 9, 1, 12, 0, 0)

    with pytest.raises(ValueError):
        QualityProbeEvent(
            event_id=event_id,
            schema_version=SCHEMA_VERSION,
            emitted_at_utc=naive,
            event_type="telemetry_probe",
        )


def test_event_rejects_empty_event_type() -> None:
    event_id, now = uuid4(), datetime.now(timezone.utc)

    with pytest.raises(ValueError):
        QualityProbeEvent(
            event_id=event_id,
            schema_version=SCHEMA_VERSION,
            emitted_at_utc=now,
            event_type="",
        )


@pytest.mark.parametrize("schema_version", [0, -1])
def test_event_rejects_a_non_positive_schema_version(schema_version: int) -> None:
    """A zero or negative version would land in silver as UInt16 garbage."""
    event_id, now = uuid4(), datetime.now(timezone.utc)

    with pytest.raises(ValueError):
        QualityProbeEvent(
            event_id=event_id,
            schema_version=schema_version,
            emitted_at_utc=now,
            event_type="telemetry_probe",
        )


def test_mapped_attributes_are_within_the_allowlist() -> None:
    assert set(to_otlp_attributes(_event())) <= ALLOWED_ATTRIBUTE_KEYS


def test_mapped_attributes_are_all_strings() -> None:
    assert all(isinstance(v, str) for v in to_otlp_attributes(_event()).values())


def test_event_id_round_trips_as_a_uuid() -> None:
    event = _event()
    assert UUID(to_otlp_attributes(event)["ssf.quality.event_id"]) == event.event_id


@pytest.mark.parametrize(
    "leaked_key",
    [
        "ssf.quality.source_text",
        "ssf.quality.translated_text",
        "ssf.quality.audio_url",
        "ssf.quality.error_message",
        "net.peer.ip",
    ],
)
def test_allowlist_rejects_content_bearing_keys(leaked_key: str) -> None:
    with pytest.raises(DisallowedTelemetryAttribute):
        enforce_allowlist({leaked_key: "anything"})


def test_allowlist_accepts_the_mapped_attributes() -> None:
    enforce_allowlist(to_otlp_attributes(_event()))


def test_event_name_is_not_an_attribute() -> None:
    """It is a top-level OTLP field mapped to the typed EventName column."""
    assert "event.name" not in ALLOWED_ATTRIBUTE_KEYS
    assert "event.name" not in to_otlp_attributes(_event())


# Whole segments, not substrings. The previous substring form rejected "ip"
# inside "pipeline" and "error" inside "error_code" -- a closed enum, not a
# message -- so it could not survive the allowlist widening past the envelope.
# The real invariant now lives in the manifest: every key declares a value
# shape, and there is no free-text kind to declare. This stays as a naming
# tripwire on top of that.
_CONTENT_SEGMENT = re.compile(
    r"(?:^|[._])(?:text|transcript|message|detail|payload|url|uri|ip|body|prompt"
    r"|email|username|useragent|token|secret)(?:[._]|$)"
)


# The kinds whose charset could hold a fragment of a sentence. NUMBER admits
# only `-?[0-9]{1,19}`, ENUM only a member of a set defined in this module, and
# UUID only a parseable uuid -- so for those three the key's *name* is
# cosmetic, and `message_count` is a count however it reads.
_TEXT_CAPABLE_KINDS = {
    AttributeKind.LABEL,
    AttributeKind.LANGUAGE,
    AttributeKind.OPAQUE_REF,
}


def test_no_text_capable_key_is_named_after_content() -> None:
    offenders = [
        key
        for key, spec in ALLOWED_ATTRIBUTES.items()
        if spec.kind in _TEXT_CAPABLE_KINDS and _CONTENT_SEGMENT.search(key)
    ]
    assert not offenders, offenders


def test_any_content_named_key_is_structurally_incapable_of_content() -> None:
    """The other half of the same invariant.

    `message_count` reads like content and is a `UInt32`. That is only safe
    because its declared kind makes text unrepresentable, so the exemption is
    asserted rather than assumed -- changing its kind to LABEL must fail here.
    """
    for key, spec in ALLOWED_ATTRIBUTES.items():
        if not _CONTENT_SEGMENT.search(key):
            continue
        assert spec.kind in {
            AttributeKind.NUMBER,
            AttributeKind.ENUM,
            AttributeKind.UUID,
        }, (key, spec.kind)


@pytest.mark.parametrize(
    "content_key",
    [
        "ssf.quality.source_text",
        "ssf.quality.asr_transcript",
        "ssf.quality.error_message",
        "ssf.quality.audio_url",
        "net.peer.ip",
        "ssf.quality.request_body",
    ],
)
def test_the_naming_tripwire_rejects_a_content_bearing_key(content_key: str) -> None:
    """Proving the guard fails: without this the regex above could match nothing."""
    assert _CONTENT_SEGMENT.search(content_key)


def test_no_attribute_may_be_declared_as_free_text() -> None:
    """The structural guarantee behind the naming tripwire."""
    assert not [k for k in dir(contract.AttributeKind) if k in ("TEXT", "FREEFORM")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("disabled", TelemetryMode.DISABLED),
        ("probe", TelemetryMode.PROBE),
        ("  PROBE  ", TelemetryMode.PROBE),
        ("true", TelemetryMode.DISABLED),
        ("enabled", TelemetryMode.ENABLED),
        ("", TelemetryMode.DISABLED),
        (None, TelemetryMode.DISABLED),
    ],
)
def test_mode_parsing_never_raises_on_operator_input(
    raw: str | None, expected: TelemetryMode
) -> None:
    """A boolean kill switch is a known trap here; so is a crash on a typo."""
    assert TelemetryMode.parse(raw) is expected


def test_mode_is_an_enum_not_a_boolean() -> None:
    with pytest.raises(ValueError):
        TelemetryMode("true")
