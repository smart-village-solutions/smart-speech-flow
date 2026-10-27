"""Merge a tenant's new-writer output into s3.json or archive-writers.json (runbook Step 5).

    sudo python3 merge_writer.py seaweedfs NEW_WRITER_JSON /etc/ssf-archive/seaweedfs/s3.json --owner 1000:1000
    sudo python3 merge_writer.py gateway NEW_WRITER_JSON /etc/ssf/recording-secrets/archive-writers.json --owner 100:101

Standard library only, so it runs on the archive VM too. The secrets go from
one file to the other and never to the screen. The target must be valid JSON
before and is rewritten atomically, mode 0400, owned by --owner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path


def _merge_seaweedfs(config: dict, new: dict) -> dict:
    identity, policy = new["seaweedfs_identity"], new["seaweedfs_policy"]
    config["identities"] = [
        i for i in config.get("identities", []) if i.get("name") != identity["name"]
    ] + [identity]
    config["policies"] = [
        p for p in config.get("policies", []) if p.get("name") != policy["name"]
    ] + [policy]
    return config


def _merge_gateway(writers: dict, new: dict) -> dict:
    return writers | new["gateway_writer"]


def _write(path: Path, content: dict, owner: tuple[int, int]) -> None:
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o400)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(content, handle, indent=2)
        handle.write("\n")
    os.chown(temporary, *owner)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_writer.py")
    parser.add_argument("target", choices=["seaweedfs", "gateway"])
    parser.add_argument("new_writer", type=Path)
    parser.add_argument("file", type=Path)
    parser.add_argument("--owner", required=True, help="UID:GID the file belongs to")
    args = parser.parse_args(argv)
    uid, _, gid = args.owner.partition(":")
    try:
        new = json.loads(args.new_writer.read_text())
        existing = json.loads(args.file.read_text()) if args.file.exists() else {}
    except ValueError:
        print(
            f"merge_writer.py: {args.file} or the new-writer file is not valid JSON",
            file=sys.stderr,
        )
        return 1
    merged = (_merge_seaweedfs if args.target == "seaweedfs" else _merge_gateway)(existing, new)
    _write(args.file, merged, (int(uid), int(gid)))
    print(f"merge_writer.py: {args.file} updated, mode 0400, owner {args.owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
