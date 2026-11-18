"""Exercise historical protocol validators in isolation from the production router."""

from fastapi import FastAPI

from services.api_gateway.routes import recording_ceremony, recording_recovery, recording_resharing

app = FastAPI()
for module in (recording_ceremony, recording_recovery, recording_resharing):
    app.include_router(module.router)
