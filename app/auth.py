from fastapi import Query, Header, HTTPException
from app.config import settings


async def verify_token(
    t: str = Query(default=""),
    authorization: str = Header(default=""),
):
    """Accept token from Authorization: Bearer header (preferred) or ?t= query param (HTML nav)."""
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = t
    if not token or token != settings.auth_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
