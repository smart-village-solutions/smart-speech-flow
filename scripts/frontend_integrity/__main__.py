"""python -m scripts.frontend_integrity record|check|alert (#620, spec §5 and §6)."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.frontend_integrity.alert import GitHubIssues, run_alert, safe
from scripts.frontend_integrity.check import confirmed
from scripts.frontend_integrity.record import dump, record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.frontend_integrity")
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record", help="record a built image as the current version")
    recording.add_argument("--image", required=True)
    recording.add_argument("--commit", required=True)
    recording.add_argument("--manifest", type=Path, required=True)
    recording.add_argument("--out", type=Path, required=True)
    checking = commands.add_parser(
        "check", help="compare the live site with the recorded fingerprint"
    )
    checking.add_argument("--url", required=True)
    checking.add_argument("--manifest", type=Path, required=True)
    checking.add_argument("--out", type=Path, required=True)
    alerting = commands.add_parser(
        "alert", help="open or update the bundle-integrity issue from a verdict"
    )
    alerting.add_argument("--verdict", type=Path, required=True)
    alerting.add_argument("--repository", required=True)
    alerting.add_argument("--label", default="bundle-integrity")
    alerting.add_argument("--assignees", default="")
    return parser


def _record(args) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = record(args.image, args.commit, args.manifest, now)
    args.out.write_text(dump(data), encoding="utf-8")
    print(f"recorded {args.image} ({len(data['current']['files'])} files) as current")
    return 0


def _check(args) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verdict = confirmed(args.url, manifest)
    args.out.write_text(json.dumps(verdict.as_json(), indent=2) + "\n")
    print(f"{verdict.outcome} {verdict.matched or ''}: {len(verdict.findings)} finding(s)")
    for finding in verdict.findings:
        print(f"  {safe(finding)}")
    return 0


def _alert(args) -> int:
    verdict = json.loads(args.verdict.read_text(encoding="utf-8"))
    issues = GitHubIssues(args.repository, os.environ.get("GH_TOKEN") or None)
    return run_alert(verdict, issues, args.label, args.assignees.replace(",", " ").split())


def main(argv=None) -> int:
    """Run one subcommand and return its exit code."""
    args = _parser().parse_args(argv)
    return {"record": _record, "check": _check, "alert": _alert}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
