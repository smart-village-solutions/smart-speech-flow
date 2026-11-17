"""Compare the live frontend with the fingerprint recorded at deploy time (#620, spec §6)."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from scripts.frontend_integrity.site import Getter, Reply, UnreachableError, fetch

CONFIRM_AFTER_SECONDS = 120
DEEP_LINK = "/join/monitor-probe"
POLICY_HEADERS = ("content-security-policy", "content-security-policy-report-only")
VERSIONS = ("current", "previous")


@dataclass(frozen=True)
class Verdict:
    outcome: str
    matched: str | None = None
    findings: tuple[str, ...] = ()

    def as_json(self) -> dict:
        """The verdict as the alert step reads it."""
        return {"outcome": self.outcome, "matched": self.matched, "findings": list(self.findings)}


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _policy(headers: dict[str, str]) -> dict[str, str]:
    return {name: headers[name] for name in POLICY_HEADERS if name in headers}


def _file_findings(base: str, files: dict[str, str], get: Getter) -> list[str]:
    findings = []
    for path, expected in files.items():
        if path == "index.html":
            continue
        reply = get(f"{base}/{quote(path)}")
        if reply.status != 200 or _digest(reply.body) != expected:
            findings.append(f"{path} differs (HTTP {reply.status})")
    return findings


def _policy_findings(entry: dict, replies: dict[str, Reply]) -> list[str]:
    expected = {entry["cspHeader"].lower(): entry["csp"]}
    findings = []
    for path, reply in replies.items():
        served = _policy(reply.headers)
        if served != expected:
            findings.append(f"the policy header on {path} differs: {sorted(served.items())}")
    return findings


def differences(entry: dict, base: str, get: Getter) -> list[str]:
    """Everything the live site serves differently from this recorded version."""
    index, deep = get(base + "/"), get(base + DEEP_LINK)
    findings = []
    if index.status != 200 or _digest(index.body) != entry["files"]["index.html"]:
        findings.append(f"index.html differs (HTTP {index.status})")
    if deep.body != index.body:
        findings.append(f"{DEEP_LINK} serves a different index.html")
    findings += _policy_findings(entry, {"/": index, DEEP_LINK: deep})
    return findings + _file_findings(base, entry["files"], get)


def _remembering(get: Getter) -> Getter:
    seen: dict[str, Reply] = {}

    def remembered(url: str) -> Reply:
        if url not in seen:
            seen[url] = get(url)
        return seen[url]

    return remembered


def check(base_url: str, manifest: dict, get: Getter = fetch) -> Verdict:
    """Match against the current version, then the previous one; report against the current one."""
    versions = [(name, manifest[name]) for name in VERSIONS if manifest.get(name)]
    if not versions:
        return Verdict("mismatch", findings=("no version is recorded",))
    base, remembered = base_url.rstrip("/"), _remembering(get)
    reported: tuple[str, ...] = ()
    try:
        for name, entry in versions:
            findings = tuple(differences(entry, base, remembered))
            if not findings:
                return Verdict("match", matched=name)
            reported = reported or findings
    except UnreachableError as error:
        # A mismatch already seen outranks a later failure to fetch an older version.
        if reported:
            return Verdict("mismatch", findings=reported)
        return Verdict("unreachable", findings=(str(error),))
    return Verdict("mismatch", findings=reported)


def confirmed(
    base_url: str,
    manifest: dict,
    get: Getter = fetch,
    wait: Callable[[float], None] = time.sleep,
) -> Verdict:
    """Anything but a match counts only if a second look, two minutes later, still sees it."""
    verdict = check(base_url, manifest, get)
    if verdict.outcome == "match":
        return verdict
    wait(CONFIRM_AFTER_SECONDS)
    return check(base_url, manifest, get)
