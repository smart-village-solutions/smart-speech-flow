"""The mock's contract v2 bodies: JSON fixtures, scenario transforms and revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
UNSUPPORTED_QUESTION: dict[str, Any] = {
    "id": "favouriteColour",
    "type": "colourPicker",
    "question": "Which colour do you like best?",
    "required": False,
}

Transform = Callable[[dict[str, Any]], None]


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


_RUNTIME: dict[str, dict[str, Any]] = {
    path.stem.removeprefix("runtime-"): _load(path.name)
    for path in sorted(FIXTURES.glob("runtime-*.json"))
}
_INSTALLATION: dict[str, Any] = _load("installation.json")
_LOGIN_DIRECTORY: list[dict[str, Any]] = _load("login-directory.json")
RUNTIME_V2_TENANTS = tuple(sorted(_RUNTIME))


def revision(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 revision of a payload's canonical JSON."""
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _storage_disabled(body: dict[str, Any]) -> None:
    body["conversationContentStorage"] = {"mode": "disabled", "retentionHours": None}
    for language in body["guestLanguages"]:
        language["guest"]["storageQuestionHtml"] = None


def _invalid_guest_form(body: dict[str, Any]) -> None:
    # The gateway drops a guest language whose form is invalid; the policy stays valid.
    form = body["guestLanguages"][0].setdefault(
        "feedback",
        {
            "headline": "Feedback",
            "questions": [],
            "noticeHtml": "<p>Test environment.</p>",
            "button": "Send",
        },
    )
    form["questions"].append(deepcopy(UNSUPPORTED_QUESTION))


def _invalid_installation_form(body: dict[str, Any]) -> None:
    body["localization"]["feedback"]["questions"].append(deepcopy(UNSUPPORTED_QUESTION))


_RUNTIME_SCENARIOS: dict[str, Transform] = {
    "storage-disabled": _storage_disabled,
    "invalid-content": _invalid_guest_form,
}
_INSTALLATION_SCENARIOS: dict[str, Transform] = {
    "invalid-content": _invalid_installation_form,
}


def _stamped(template: dict[str, Any], transform: Transform | None) -> dict[str, Any]:
    body = deepcopy(template)
    if transform is not None:
        transform(body)
    body["configurationRevision"] = revision(body)
    return body


def runtime_configuration_v2(tenant_id: str, scenario: str | None) -> dict[str, Any]:
    """Return one tenant's v2 body after the scenario's transform; KeyError if unknown."""
    return _stamped(_RUNTIME[tenant_id], _RUNTIME_SCENARIOS.get(scenario or ""))


def installation_content_v2(scenario: str | None) -> dict[str, Any]:
    """Return the installation content v2 body after the scenario's transform."""
    return _stamped(_INSTALLATION, _INSTALLATION_SCENARIOS.get(scenario or ""))


def login_directory_tenants() -> list[dict[str, Any]]:
    """Return the tenants the login directory lists, as a fresh copy."""
    return deepcopy(_LOGIN_DIRECTORY)
