import json
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_token
from app.config import settings as _settings  # noqa: used in _resolve_working_dir
from app.database import get_db
import app.database as _db_module
from app.models import Channel, Message
from app.services.opencode import stream_opencode

router = APIRouter(dependencies=[Depends(verify_token)])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ── HTML page ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html")


# ── REST: channels ────────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    name: str
    working_dir: str | None = None


@router.get("/api/channels")
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).order_by(Channel.created_at))
    channels = result.scalars().all()
    return [
        {"id": c.id, "name": c.name, "working_dir": c.working_dir, "created_at": c.created_at}
        for c in channels
    ]


def _resolve_working_dir(working_dir: str | None) -> str | None:
    if not working_dir:
        return None
    p = Path(working_dir)
    if not p.is_absolute() and _settings.workspaces_dir:
        p = Path(_settings.workspaces_dir) / p
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


@router.post("/api/channels", status_code=201)
async def create_channel(body: ChannelCreate, db: AsyncSession = Depends(get_db)):
    channel = Channel(name=body.name, working_dir=_resolve_working_dir(body.working_dir))
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return {"id": channel.id, "name": channel.name, "working_dir": channel.working_dir, "created_at": channel.created_at}


@router.delete("/api/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.execute(delete(Message).where(Message.channel_id == channel_id))
    await db.delete(channel)
    await db.commit()


@router.get("/api/channels/{channel_id}/messages")
async def get_messages(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")
    msgs = await db.execute(
        select(Message).where(Message.channel_id == channel_id).order_by(Message.created_at)
    )
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in msgs.scalars().all()
    ]


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/chat/{channel_id}")
async def ws_chat(websocket: WebSocket, channel_id: str, t: str = ""):
    from app.config import settings as _settings
    if t != _settings.auth_token:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Use a fresh DB session for the WS lifetime (via module ref so tests can patch it)
    async with _db_module.async_session_factory() as db:
        result = await db.execute(select(Channel).where(Channel.id == channel_id))
        channel = result.scalar_one_or_none()
        if not channel:
            await websocket.send_json({"type": "error", "message": "Channel not found"})
            await websocket.close()
            return

        # Send history
        msgs = await db.execute(
            select(Message).where(Message.channel_id == channel_id).order_by(Message.created_at)
        )
        for m in msgs.scalars().all():
            await websocket.send_json({"type": "history", "role": m.role, "content": m.content, "id": m.id})

        try:
            while True:
                data = await websocket.receive_json()
                user_text = data.get("message", "").strip()
                if not user_text:
                    continue

                # Persist user message
                user_msg = Message(channel_id=channel_id, role="user", content=user_text)
                db.add(user_msg)
                await db.commit()
                await db.refresh(user_msg)
                await websocket.send_json({"type": "user", "content": user_text, "id": user_msg.id})

                # Stream opencode response
                await websocket.send_json({"type": "assistant_start"})
                response_parts: list[str] = []
                try:
                    async for chunk, sid in stream_opencode(
                        user_text,
                        session_id=channel.opencode_session_id,
                        working_dir=channel.working_dir,
                    ):
                        if sid and channel.opencode_session_id != sid:
                            channel.opencode_session_id = sid
                            await db.commit()
                        if chunk:
                            response_parts.append(chunk)
                            await websocket.send_json({"type": "chunk", "content": chunk})
                except RuntimeError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                    continue

                full_response = "".join(response_parts)
                asst_msg = Message(channel_id=channel_id, role="assistant", content=full_response)
                db.add(asst_msg)
                await db.commit()
                await db.refresh(asst_msg)
                await websocket.send_json({"type": "assistant_end", "id": asst_msg.id})

        except WebSocketDisconnect:
            pass
