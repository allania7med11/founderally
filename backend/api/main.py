"""The API: starts, signals and reads runs. Runs nothing long.

Every route lives under /api: the gateway sends that prefix here and / to the web app.
Logging is set by logging.json, passed to uvicorn with --log-config.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from settings import settings

from api.runs import router as runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Read the environment at boot: a missing variable stops the container, not the first request.
    settings()
    yield


app = FastAPI(title="FounderAlly API", lifespan=lifespan)
app.include_router(runs)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
