"""What every route needs before its body runs: who is asking, the run they name, and the Temporal client.

The tenant is never in a body or a URL. Until auth lands it is the `X-Tenant-Id` header, read here and nowhere else;
the session cookie replaces this one function later and no route changes.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from temporalio.client import Client

from db.engine import engine
from db.models import Run
from settings import settings


async def tenant_id(x_tenant_id: Annotated[str, Header()]) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id must be a UUID") from None


Tenant = Annotated[uuid.UUID, Depends(tenant_id)]


async def load_run(run_id: uuid.UUID, tenant: Tenant) -> Run:
    """The run named in the path, if it belongs to the caller. Not theirs reads the same as not there: 404."""
    async with engine().connect() as conn:
        row = (await conn.execute(select(Run).where(Run.run_id == run_id, Run.tenant_id == tenant))).first()
    if row is None:
        raise HTTPException(404, "run not found")
    return row


OwnedRun = Annotated[Run, Depends(load_run)]


async def temporal(request: Request) -> Client:
    """One client per process, connected on first use (like `engine()`), so the API boots before Temporal answers."""
    client = getattr(request.app.state, "temporal", None)
    if client is None:
        s = settings()
        client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
        request.app.state.temporal = client
    return client


Temporal = Annotated[Client, Depends(temporal)]
