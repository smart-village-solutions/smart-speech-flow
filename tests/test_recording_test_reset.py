"""Reset planning rejects accidental live-generation or wrong-target destruction."""

import pytest

from services.api_gateway.recording.reset_legacy_test_data import (
    ResetRefusedError,
    confirm_plan,
    deletion_order,
)


def test_apply_confirmation_binds_database_tenant_and_inventory():
    plan = {
        "database": "recording_test",
        "tenant": "tenant-a",
        "digest": "012345",
        "generation": 1,
        "storageTarget": "s3://test/bucket",
    }
    with pytest.raises(ResetRefusedError):
        confirm_plan(plan, "recording_test:tenant-b:012345", True)
    with pytest.raises(ResetRefusedError):
        confirm_plan(plan, "recording_test:tenant-a:stale", True)
    with pytest.raises(ResetRefusedError):
        confirm_plan(plan, "recording_test:tenant-a:012345", False)
    confirm_plan(plan, "recording_test:tenant-a:012345", True)


def test_generation_two_never_counts_as_disposable_legacy():
    plan = {"database": "db", "tenant": "t", "digest": "d", "generation": 2}
    with pytest.raises(ResetRefusedError):
        confirm_plan(plan, "db:t:d", True)


def test_dependent_rows_are_deleted_before_their_parent():
    order = deletion_order({"keys", "wraps", "notes"}, [("notes", "wraps"), ("wraps", "keys")])
    assert order == ["notes", "wraps", "keys"]
    with pytest.raises(ResetRefusedError):
        deletion_order({"keys", "wraps"}, [("keys", "wraps"), ("wraps", "keys")])
    with pytest.raises(ResetRefusedError):
        deletion_order({"keys"}, [("unknown_table", "keys")])
