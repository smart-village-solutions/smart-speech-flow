"""One spool per tenant: a fault stays with the tenant that has it (spec §12.3)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from services.api_gateway.recording.storage.archive import (
    ArchiveRefusedError,
    object_key,
)
from services.api_gateway.recording.storage.filesystem import FilesystemArchiveStore
from services.api_gateway.recording.storage.tenant_spools import TenantSpools
from services.api_gateway.session_pseudonym import tenant_ref

KEY = object_key(
    "0d6c2b1a-9e8f-4d7c-b6a5-000000000001", "1e7d3c2b-0f9e-4e8d-a7b6-5a4f3e2d1c0b", "record.json"
)


class BrokenFor:
    """A store that refuses one tenant, as a missing bucket or credential would."""

    def __init__(self, inner, broken_tenant):
        self.inner, self.broken = inner, broken_tenant

    async def put(self, tenant_id, key, data):
        if tenant_id == self.broken:
            raise ArchiveRefusedError("NoSuchBucket")
        return await self.inner.put(tenant_id, key, data)

    async def head(self, tenant_id, key):
        return await self.inner.head(tenant_id, key)

    async def get(self, tenant_id, key, version_id):
        return await self.inner.get(tenant_id, key, version_id)


def _spools(tmp_path, writer=None, **options):
    stored: list[tuple[str, str]] = []

    async def on_stored(item, version):
        stored.append((item.tenant_id, version.version_id))

    store = FilesystemArchiveStore(tmp_path / "store", timedelta(days=1))
    spools = TenantSpools(tmp_path / "spool", writer or store, on_stored, **options)
    return spools, stored


def test_each_tenant_spools_into_its_own_directory_named_by_its_reference(tmp_path):
    spools, _ = _spools(tmp_path)

    spools.spool("tenant-a").submit("tenant-a", KEY, b"a")
    spools.spool("tenant-b").submit("tenant-b", KEY, b"b")

    assert sorted(path.name for path in (tmp_path / "spool").iterdir()) == sorted(
        [tenant_ref("tenant-a"), tenant_ref("tenant-b")]
    )


def test_a_tenant_whose_store_refuses_does_not_hold_up_another(tmp_path):
    store = FilesystemArchiveStore(tmp_path / "store", timedelta(days=1))
    spools, stored = _spools(tmp_path, BrokenFor(store, "tenant-a"))
    spools.spool("tenant-a").submit("tenant-a", KEY, b"a")
    spools.spool("tenant-b").submit("tenant-b", KEY, b"b")

    assert asyncio.run(spools.flush()) is False

    assert [tenant for tenant, _ in stored] == ["tenant-b"]
    assert spools.spool("tenant-a").pending == 1
    assert spools.spool("tenant-b").pending == 0


def test_readiness_is_room_for_one_more_message_in_that_tenants_spool(tmp_path):
    spools, _ = _spools(tmp_path, capacity_bytes=100, headroom_bytes=40)

    spools.spool("tenant-a").submit("tenant-a", KEY, b"x" * 61)

    assert not spools.ready("tenant-a")
    assert spools.ready("tenant-b")


def test_a_restart_recovers_every_tenants_spool_and_uploads_it(tmp_path):
    spools, _ = _spools(tmp_path)
    spools.spool("tenant-a").submit("tenant-a", KEY, b"a")

    restarted, stored = _spools(tmp_path)
    restarted.recover()

    assert asyncio.run(restarted.flush()) is True
    assert [tenant for tenant, _ in stored] == ["tenant-a"]


def test_started_uploaders_drain_a_submit_without_a_flush(tmp_path):
    spools, stored = _spools(tmp_path)

    async def scenario():
        spools.start()
        spool = spools.spool("tenant-a")
        await asyncio.to_thread(spool.submit, "tenant-a", KEY, b"a")
        spools.notify("tenant-a")
        for _ in range(200):
            if stored:
                break
            await asyncio.sleep(0.01)
        await spools.stop()

    asyncio.run(scenario())

    assert [tenant for tenant, _ in stored] == ["tenant-a"]
