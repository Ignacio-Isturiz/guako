"""GET /api/admin/usage: what each provider served today, the spending of the period and the router's state.

Only for superusers (``users.is_superuser``). A normal account gets 403; registration cannot set the flag.
To make an account an admin, once, from the host:
    docker exec guako-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "update \\"user\\" set is_superuser = true where email = $$you@example.com$$"'
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import User, get_async_session
from app.providers.state import get_state
from app.providers.usage import flush_usage, usage_for_day
from app.users import current_superuser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/usage")
async def usage(
    _admin: Annotated[User, Depends(current_superuser)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict:
    state = get_state()
    # Write what is still in memory so the day's rows are complete.
    await flush_usage(async_sessionmaker(db.bind, expire_on_commit=False), state)
    day = state.today()
    providers = await usage_for_day(db, day)
    return {
        "day": day.isoformat(),
        "providers": providers,
        "totals": {
            "requests": sum(p["requests"] for p in providers),
            "cost_usd": round(sum(p["cost_usd"] for p in providers), 6),
        },
        **state.snapshot(),  # budget (spent, limit, status), breakers, daily caps
    }
