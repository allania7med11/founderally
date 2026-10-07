"""The API: starts, signals and reads runs. Runs nothing long.

Every route lives under /api: the gateway sends that prefix here and / to the web app.
Logging is set by logging.json, passed to uvicorn with --log-config.
"""

from fastapi import FastAPI

app = FastAPI(title="FounderAlly API")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
