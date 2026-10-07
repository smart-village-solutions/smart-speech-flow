"""Shared builders for the runtime-policy suites."""

from typing import Literal

from services.api_gateway.studio_v2 import Branding, RuntimeContent, RuntimePolicy, RuntimeRead

REVISION = "sha256:" + "c" * 64


class _ModeDefault:
    """Retention as the contract requires it for the mode."""


_MODE_DEFAULT = _ModeDefault()


def runtime_read(
    tenant_id: str = "tenant-kassel",
    mode: Literal["ask", "disabled"] = "ask",
    *,
    retention_hours: int | None | _ModeDefault = _MODE_DEFAULT,
    revision: str = REVISION,
) -> RuntimeRead:
    """A validated v2 read with empty content: the policy is all these suites need.

    Retention defaults to what the contract requires for the mode: 4320 hours
    for `ask`, none for `disabled`.
    """
    if isinstance(retention_hours, _ModeDefault):
        retention_hours = 4320 if mode == "ask" else None
    return RuntimeRead(
        policy=RuntimePolicy(
            contract_version="2.0",
            configuration_revision=revision,
            tenant_id=tenant_id,
            mode=mode,
            retention_hours=retention_hours,
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
