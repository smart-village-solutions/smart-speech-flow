"""Single-use, scoped realtime capability tickets."""

from datetime import datetime, timedelta, timezone

from services.api_gateway.realtime_ticket import RealtimeTicketStore
from services.api_gateway.tenant_session import TenantSessionKey


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key, value, *, ex, nx):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script, number_of_keys, key):
        assert number_of_keys == 1
        value = self.values.get(key)
        self.values.pop(key, None)
        return value

    def get(self, key):
        return self.values.get(key)


def test_ticket_is_hashed_scoped_and_single_use() -> None:
    redis = FakeRedis()
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    store = RealtimeTicketStore(redis, clock=lambda: now)
    key_a = TenantSessionKey("tenant-a", "ABC12345")
    key_b = TenantSessionKey("tenant-b", "ABC12345")

    issued = store.issue(key_a, "websocket", ttl_seconds=60)

    assert issued.ticket not in "".join(redis.values)
    assert issued.expires_at == now + timedelta(seconds=60)
    assert store.consume(issued.ticket, key_b, "websocket") is False
    assert store.consume(issued.ticket, key_a, "websocket") is False


def test_ticket_rejects_transport_mismatch_and_replay() -> None:
    redis = FakeRedis()
    store = RealtimeTicketStore(redis)
    key = TenantSessionKey("tenant-a", "ABC12345")
    wrong_transport = store.issue(key, "websocket")
    valid = store.issue(key, "websocket")

    assert store.consume(wrong_transport.ticket, key, "polling") is False
    assert store.consume(valid.ticket, key, "websocket") is True
    assert store.consume(valid.ticket, key, "websocket") is False


def test_session_revocation_invalidates_every_outstanding_ticket() -> None:
    redis = FakeRedis()
    store = RealtimeTicketStore(redis)
    key = TenantSessionKey("tenant-a", "ABC12345")
    first = store.issue(key, "websocket")
    second = store.issue(key, "polling")

    store.revoke(key)

    assert store.consume(first.ticket, key, "websocket") is False
    assert store.consume(second.ticket, key, "polling") is False
