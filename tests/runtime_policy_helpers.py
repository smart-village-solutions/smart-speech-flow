"""Shared builders for the runtime-policy suites."""

from services.api_gateway.studio_runtime_client import RuntimeConfiguration

REVISION = "sha256:" + "c" * 64


def configuration(tenant_id: str = "tenant-kassel", mode: str = "ask"):
    question = "<p>Store?</p>" if mode == "ask" else None
    return RuntimeConfiguration.model_validate(
        {
            "contractVersion": "1.0",
            "configurationRevision": REVISION,
            "authorizationRevision": REVISION,
            "tenant": {
                "id": tenant_id,
                "displayName": "Kassel",
                "timeZone": "Europe/Berlin",
            },
            "branding": {"logo": None, "icon": None},
            "localization": {
                "defaultLocale": "de",
                "locales": [
                    {
                        "locale": "de",
                        "authenticatedHomeExplanationHtml": "<p>a</p>",
                        "guestExplanationHtml": "<p>b</p>",
                        "conversationContentStorageQuestionHtml": question,
                    }
                ],
            },
            "conversationContentStorage": {"mode": mode},
        }
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
