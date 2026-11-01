"""Shared builders for the runtime-policy suites."""

from services.api_gateway.studio_v2 import Branding, RuntimeContent, RuntimePolicy, RuntimeRead

REVISION = "sha256:" + "c" * 64


def runtime_read(tenant_id: str = "tenant-kassel", *, revision: str = REVISION) -> RuntimeRead:
    """A validated v2 read with empty content: the policy is all these suites need."""
    return RuntimeRead(
        policy=RuntimePolicy(
            contract_version="2.0",
            configuration_revision=revision,
            tenant_id=tenant_id,
        ),
        content=RuntimeContent(
            display_name=None,
            time_zone=None,
            branding=Branding(),
            staff=None,
            guest_languages=(),
        ),
    )


class RecordingClient:
    """A fetcher that counts reads and replays a scripted sequence."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def fetch(self, tenant_id: str, correlation_id: str):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
