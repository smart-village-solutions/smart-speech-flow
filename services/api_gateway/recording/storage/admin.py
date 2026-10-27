"""Operator commands for the archive store (runbook archive-storage-deployment.md).

    python -m services.api_gateway.recording.storage.admin new-writer TENANT_ID
    python -m services.api_gateway.recording.storage.admin create-bucket TENANT_ID --retention-hours H
    python -m services.api_gateway.recording.storage.admin check

`new-writer` makes a tenant's writer credential and prints the SeaweedFS
identity, its policy, and the gateway's writers-file entry for it.
`create-bucket` needs the storage admin credential in
SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID and SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY, given
for that one run only. `check` uses the gateway's own configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from collections.abc import Sequence
from typing import Final

from ...session_pseudonym import tenant_ref
from ...studio_v1 import is_printable_ascii
from .archive import ArchiveError, bucket_for
from .s3 import S3ArchiveAdmin, S3Client, S3Transport, read_default_retention
from .settings import ARCHIVE_ENDPOINT_ENV, ArchiveConfigError, ArchiveSettings
from .sigv4 import Credentials

ADMIN_KEY_ENV: Final[str] = "SSF_ARCHIVE_ADMIN_ACCESS_KEY_ID"
ADMIN_SECRET_ENV: Final[str] = "SSF_ARCHIVE_ADMIN_SECRET_ACCESS_KEY"


def default_retention_days(retention_hours: int) -> int:
    """Whole days covering the tenant's retention, plus one: the lock may outlast it, never fall short."""
    if retention_hours < 1:
        raise ValueError("the retention is at least one hour")
    return -(-retention_hours // 24) + 1


def writer_policy(bucket: str) -> dict[str, object]:
    """Named S3 actions, because SeaweedFS's legacy `Write` grant also allows lifecycle and CORS changes."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketObjectLockConfiguration"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
        ],
    }


def new_writer(tenant_id: str) -> dict[str, object]:
    if not is_printable_ascii(tenant_id):
        raise ValueError("the tenant ID must be printable ASCII")
    bucket = bucket_for(tenant_id)
    name = f"writer-{tenant_ref(tenant_id)}"
    access_key = "ssfw" + secrets.token_hex(8)
    secret_key = secrets.token_urlsafe(32)
    return {
        "seaweedfs_identity": {
            "name": name,
            "credentials": [{"accessKey": access_key, "secretKey": secret_key}],
            "policyNames": [name],
        },
        "seaweedfs_policy": {"name": name, "document": writer_policy(bucket)},
        "gateway_writer": {
            tenant_id: {"access_key_id": access_key, "secret_access_key": secret_key}
        },
    }


async def create_bucket(
    tenant_id: str, retention_hours: int, transport: S3Transport | None = None
) -> str:
    endpoint = os.environ.get(ARCHIVE_ENDPOINT_ENV, "").strip()
    key, secret = os.environ.get(ADMIN_KEY_ENV, ""), os.environ.get(ADMIN_SECRET_ENV, "")
    if not (endpoint and key and secret):
        raise ArchiveConfigError(
            f"set {ARCHIVE_ENDPOINT_ENV}, {ADMIN_KEY_ENV} and {ADMIN_SECRET_ENV} for this command"
        )
    days = default_retention_days(retention_hours)
    client = S3Client(endpoint, transport=transport)
    try:
        admin = S3ArchiveAdmin(client, Credentials(key, secret))
        bucket = await admin.create_bucket(tenant_id)
        previous = await admin.default_retention_days(tenant_id)
        await admin.set_default_retention(tenant_id, days)
        now = await admin.default_retention_days(tenant_id)
    finally:
        await client.close()
    was = "new" if previous is None else f"was {previous}"
    return f"{bucket}: object lock on, default compliance retention {now} days ({was})"


async def check(settings: ArchiveSettings, transport: S3Transport | None = None) -> list[str]:
    """One line per tenant; raises nothing so every tenant is reported."""
    client = S3Client(settings.endpoint, transport=transport)
    lines = []
    try:
        for tenant_id, credentials in sorted(settings.writers.items()):
            bucket = bucket_for(tenant_id)
            try:
                await client.request(credentials, "GET", bucket, query={"max-keys": "1"})
                mode, days = await read_default_retention(client, credentials, tenant_id)
            except ArchiveError as error:
                lines.append(f"FAIL  {tenant_id} {bucket} {error.code}")
                continue
            if mode != "COMPLIANCE" or not days:
                lines.append(f"FAIL  {tenant_id} {bucket} no_default_retention")
            else:
                lines.append(f"ok    {tenant_id} {bucket} {days} days")
    finally:
        await client.close()
    return lines


def _check_configured() -> list[str]:
    settings = ArchiveSettings.from_environment()
    if settings is None:
        raise ArchiveConfigError(f"{ARCHIVE_ENDPOINT_ENV} is not set")
    if not settings.writers:
        raise ArchiveConfigError("no tenant has a writer credential")
    return asyncio.run(check(settings))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archive-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("new-writer").add_argument("tenant_id")
    create = commands.add_parser("create-bucket")
    create.add_argument("tenant_id")
    create.add_argument("--retention-hours", type=int, required=True)
    commands.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.command == "new-writer":
            print(json.dumps(new_writer(args.tenant_id), indent=2))
            return 0
        if args.command == "create-bucket":
            print(asyncio.run(create_bucket(args.tenant_id, args.retention_hours)))
            return 0
        lines = _check_configured()
    except (ArchiveConfigError, ArchiveError, ValueError) as error:
        print(f"archive-admin: {error}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0 if all(line.startswith("ok") for line in lines) else 1


if __name__ == "__main__":
    sys.exit(main())
