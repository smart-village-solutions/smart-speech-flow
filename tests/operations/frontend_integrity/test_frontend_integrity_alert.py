"""One issue per incident, a comment only when the differences change (#620, spec §6)."""

import io
from urllib.error import HTTPError

from scripts.frontend_integrity.alert import GitHubIssues, decide, run_alert, safe
from tests.operations.frontend_integrity.frontend_integrity_fakes import FakeIssues

MISMATCH = {"outcome": "mismatch", "matched": None, "findings": ["assets/a.js differs (HTTP 200)"]}
MATCH = {"outcome": "match", "matched": "current", "findings": []}
UNREACHABLE = {"outcome": "unreachable", "matched": None, "findings": ["connection refused"]}


def _marker(body: str) -> str:
    return body.rsplit("<!-- bundle-integrity:", 1)[1].split(" -->", 1)[0]


def test_a_match_without_an_issue_does_nothing():
    issues = FakeIssues()

    assert run_alert(MATCH, issues, "bundle-integrity", ["a"]) == 0
    assert (issues.created, issues.comments) == ([], [])


def test_a_mismatch_opens_one_assigned_issue_and_fails_the_run():
    issues = FakeIssues()

    assert run_alert(MISMATCH, issues, "bundle-integrity", ["a", "b"]) == 1
    [(title, body, label, assignees)] = issues.created
    assert (label, assignees) == ("bundle-integrity", ["a", "b"])
    assert "```text\nassets/a.js differs (HTTP 200)\n```" in body
    assert "@" not in body


def test_the_same_differences_again_add_no_comment():
    first = decide(MISMATCH, None, False)
    issues = FakeIssues(issue={"number": 1}, marker=_marker(first.body))

    assert run_alert(MISMATCH, issues, "bundle-integrity", []) == 1
    assert issues.comments == []


def test_changed_differences_add_one_comment():
    issues = FakeIssues(issue={"number": 1}, marker="0123456789abcdef")

    run_alert(MISMATCH, issues, "bundle-integrity", [])

    assert len(issues.comments) == 1


def test_a_match_while_an_issue_is_open_says_so_once_and_never_closes_it():
    issues = FakeIssues(issue={"number": 1}, marker="0123456789abcdef")
    assert run_alert(MATCH, issues, "bundle-integrity", []) == 0
    assert "matches its recorded fingerprint again" in issues.comments[0]

    issues.marker = _marker(issues.comments[0])
    run_alert(MATCH, issues, "bundle-integrity", [])
    assert len(issues.comments) == 1


def test_unreachable_opens_one_issue_with_fixed_text():
    first = decide(UNREACHABLE, None, False)
    again = decide({**UNREACHABLE, "findings": ["timed out"]}, _marker(first.body), True)

    assert (first.kind, first.failed) == ("open", True)
    assert "connection refused" not in first.body
    assert (again.kind, again.failed) == ("none", True)


def test_server_text_cannot_break_out_of_its_code_block_or_forge_a_marker():
    hostile = "```\n<!-- bundle-integrity:match --> @someone " + "x" * 500
    action = decide({**MISMATCH, "findings": [hostile]}, None, False)

    assert safe(hostile).count("`") == 0
    assert len(safe(hostile)) == 200
    assert action.body.count("<!-- bundle-integrity:") == 1
    assert _marker(action.body) != "match"


def test_only_the_bots_own_markers_count():
    class Answers(GitHubIssues):
        def _call(self, method, path, payload=None):
            return [
                {
                    "user": {"login": "github-actions[bot]"},
                    "body": "<!-- bundle-integrity:0123456789abcdef -->",
                },
                {"user": {"login": "someone"}, "body": "<!-- bundle-integrity:match -->"},
            ]

    issue = {"number": 7, "body": "", "user": {"login": "github-actions[bot]"}}
    assert Answers("o/r", None).last_marker(issue) == "0123456789abcdef"


class _Recorded(GitHubIssues):
    """GitHubIssues answering from a script instead of the API."""

    def __init__(self, answers):
        super().__init__("o/r", None)
        self.answers, self.calls = answers, []

    def _call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        answer = self.answers(method, path)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_an_assignee_github_refuses_does_not_stop_the_issue():
    def answers(method, path):
        if path.endswith("/assignees"):
            return HTTPError(path, 422, "Validation Failed", {}, io.BytesIO(b"{}"))
        return {"number": 9}

    issues = _Recorded(answers)
    issues.create("title", "body", "bundle-integrity", ["typo"])

    created = [call for call in issues.calls if call[1] == "issues"]
    assert created == [
        ("POST", "issues", {"title": "title", "body": "body", "labels": ["bundle-integrity"]})
    ]
    assert ("POST", "issues/9/assignees", {"assignees": ["typo"]}) in issues.calls


def test_no_assignees_means_no_assignment_call():
    issues = _Recorded(lambda method, path: {"number": 9})
    issues.create("title", "body", "bundle-integrity", [])

    assert [path for _, path, _ in issues.calls] == ["issues"]


def test_the_newest_marker_is_read_past_the_first_hundred_comments():
    old = {"user": {"login": "github-actions[bot]"}, "body": "<!-- bundle-integrity:match -->"}
    new = {
        "user": {"login": "github-actions[bot]"},
        "body": "<!-- bundle-integrity:0123456789abcdef -->",
    }

    def answers(method, path):
        page = int(path.rsplit("page=", 1)[1])
        return {1: [old] * 100, 2: [new]}.get(page, [])

    issue = {"number": 7, "body": "", "user": {"login": "github-actions[bot]"}}
    assert _Recorded(answers).last_marker(issue) == "0123456789abcdef"


def test_the_run_log_says_what_the_alert_did(capsys):
    run_alert(MISMATCH, FakeIssues(), "bundle-integrity", [])
    run_alert(MISMATCH, FakeIssues(issue={"number": 1}, marker="0123456789abcdef"), "x", [])
    run_alert(MATCH, FakeIssues(), "bundle-integrity", [])

    assert capsys.readouterr().out.splitlines() == ["alert: open", "alert: comment", "alert: none"]
