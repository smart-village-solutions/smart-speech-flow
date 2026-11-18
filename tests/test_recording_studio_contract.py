"""Studio consumes this versioned schema independently of a running Gateway."""

import json
from pathlib import Path

from fastapi import FastAPI

from services.api_gateway.routes.recording_organisation_keys import router


def schema():
    api = FastAPI(title="SSF recording organisation keys and transfers", version="2")
    api.include_router(router, prefix="/api/admin/recording")
    return api.openapi()


def test_published_studio_schema_matches_registered_routes():
    published = Path(__file__).parent / "fixtures/recording/studio_gateway_v2.openapi.json"
    assert json.loads(published.read_text()) == schema()
    for methods in schema()["paths"].values():
        for operation in methods.values():
            response = operation["responses"].get("200")
            if response:
                assert "$ref" in response["content"]["application/json"]["schema"]
