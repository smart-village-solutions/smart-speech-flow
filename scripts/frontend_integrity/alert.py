"""Turn a verdict into at most one issue action (#620, spec §6)."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen

MAX_FINDINGS = 40
MAX_FINDING_LENGTH = 200
BOT = "github-actions[bot]"
MATCH = "match"
MANIFEST = "deploy/production/frontend-manifest.json"
RUNBOOK = "docs/operations/runbooks/frontend-bundle-integrity.md"
TITLE = "Frontend bundle does not match its recorded fingerprint"
UNREACHABLE_FINDING = (
    "the site did not answer GitHub's runners twice, two minutes apart (the run log has the error)"
)
COMMENTS_PER_PAGE = 100
_MARKER = re.compile(r"<!-- bundle-integrity:([0-9a-f]{16}|match) -->")


@dataclass(frozen=True)
class Action:
    kind: str
    body: str = ""
    failed: bool = False


def _marker(value: str) -> str:
    return f"<!-- bundle-integrity:{value} -->"


def safe(text: str) -> str:
    """Printable ASCII only, no backticks, angle brackets or @, at most 200 characters."""
    return "".join(c if " " <= c <= "~" and c not in "`<>@" else "'" for c in text)[
        :MAX_FINDING_LENGTH
    ]


def _report(findings: list[str], fingerprint: str) -> str:
    lines = [safe(finding) for finding in findings[:MAX_FINDINGS]]
    if len(findings) > MAX_FINDINGS:
        lines.append(f"... and {len(findings) - MAX_FINDINGS} more")
    return "\n".join(
        [
            f"The live frontend does not match the fingerprint recorded in {MANIFEST}.",
            "",
            "```text",
            *lines,
            "```",
            "",
            f'Respond as described in {RUNBOOK}, "Responding to an alert". Close this issue only after checking.',
            "",
            _marker(fingerprint),
        ]
    )


MATCHES_AGAIN = (
    "The live frontend matches its recorded fingerprint again. "
    "Close this issue only once the cause is understood.\n\n" + _marker(MATCH)
)


def _mismatch(findings: list[str], open_marker: str | None, issue_open: bool) -> Action:
    fingerprint = hashlib.sha256("\n".join(sorted(findings)).encode()).hexdigest()[:16]
    if not issue_open:
        return Action("open", _report(findings, fingerprint), failed=True)
    if open_marker != fingerprint:
        return Action("comment", _report(findings, fingerprint), failed=True)
    return Action("none", failed=True)


def decide(verdict: dict, open_marker: str | None, issue_open: bool) -> Action:
    """Return what to do about this verdict, given the open issue's last marker."""
    outcome = verdict["outcome"]
    if outcome == "unreachable":
        return _mismatch([UNREACHABLE_FINDING], open_marker, issue_open)
    if outcome == "mismatch":
        return _mismatch(verdict["findings"], open_marker, issue_open)
    if outcome != MATCH:
        raise ValueError(f"unknown outcome {outcome!r}")
    if issue_open and open_marker != MATCH:
        return Action("comment", MATCHES_AGAIN)
    return Action("none")


class Issues(Protocol):
    def find_open(self, label: str) -> dict | None: ...

    def last_marker(self, issue: dict) -> str | None: ...

    def create(self, title: str, body: str, label: str, assignees: list[str]) -> None: ...

    def comment(self, issue: dict, body: str) -> None: ...


class GitHubIssues:
    """The repository's issues through the REST API, with the workflow's token."""

    def __init__(self, repository: str, token: str | None):
        self.repository = repository
        self.token = token

    def _call(self, method: str, path: str, payload: dict | None = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"https://api.github.com/repos/{self.repository}/{path}", data, headers, method=method
        )
        with urlopen(request, timeout=30) as reply:
            return json.load(reply)

    def find_open(self, label: str) -> dict | None:
        """Return the oldest open issue with this label that the workflow opened."""
        issues = self._call("GET", f"issues?labels={quote(label)}&state=open&per_page=20")
        own = [
            issue
            for issue in issues
            if "pull_request" not in issue and issue["user"]["login"] == BOT
        ]
        return min(own, key=lambda issue: issue["number"]) if own else None

    def last_marker(self, issue: dict) -> str | None:
        """Return the newest marker the workflow itself wrote on this issue."""
        comments, page = [], 1
        while True:
            batch = self._call(
                "GET",
                f"issues/{issue['number']}/comments?per_page={COMMENTS_PER_PAGE}&page={page}",
            )
            comments += batch
            if len(batch) < COMMENTS_PER_PAGE:
                break
            page += 1
        bodies = [issue.get("body") or ""] + [
            c["body"] or "" for c in comments if c["user"]["login"] == BOT
        ]
        markers = [marker for body in bodies for marker in _MARKER.findall(body)]
        return markers[-1] if markers else None

    def create(self, title: str, body: str, label: str, assignees: list[str]) -> None:
        """Open the issue, then assign it: a login GitHub refuses must not stop the alarm."""
        created = self._call("POST", "issues", {"title": title, "body": body, "labels": [label]})
        if not assignees:
            return
        try:
            self._call("POST", f"issues/{created['number']}/assignees", {"assignees": assignees})
        except OSError as error:  # HTTPError and URLError included
            print(f"could not assign {assignees}: {error}")

    def comment(self, issue: dict, body: str) -> None:
        """Comment on the open issue."""
        self._call("POST", f"issues/{issue['number']}/comments", {"body": body})


def run_alert(verdict: dict, issues: Issues, label: str, assignees: list[str]) -> int:
    """Act on a verdict; return 1 whenever the run must fail."""
    issue = issues.find_open(label)
    marker = issues.last_marker(issue) if issue else None
    action = decide(verdict, marker, issue is not None)
    if action.kind == "open":
        issues.create(TITLE, action.body, label, assignees)
    elif action.kind == "comment":
        issues.comment(issue, action.body)
    print(f"alert: {action.kind}")
    return 1 if action.failed else 0
