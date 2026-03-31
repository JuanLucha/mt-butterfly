from fastapi import Query, HTTPException
from app.config import settings


async def verify_token(t: str = Query(default="")):
    if t != settings.auth_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
