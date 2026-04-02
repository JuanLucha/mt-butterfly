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
ws_router = APIRouter()  # WebSocket router — no router-level auth (handler does its own handshake)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Active WebSocket connections per channel — supports multiple devices on the same channel
_connections: dict[str, set[WebSocket]] = {}


async def _broadcast(channel_id: str, data: dict, exclude: WebSocket | None = None) -> None:
    """Send data to all connected WebSockets for channel_id, optionally excluding one."""
    for ws in list(_connections.get(channel_id, set())):
        if ws is not exclude:
            try:
                await ws.send_json(data)
            except Exception:
                pass


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
async def get_messages(
    channel_id: str,
    before: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Channel not found")

    query = select(Message).where(Message.channel_id == channel_id)

    if before:
        before_result = await db.execute(select(Message).where(Message.id == before))
        before_msg = before_result.scalar_one_or_none()
        if before_msg:
            query = query.where(Message.created_at < before_msg.created_at)

    query = query.order_by(Message.created_at.desc()).limit(limit)
    msgs = await db.execute(query)
    messages = list(reversed(msgs.scalars().all()))
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
        for m in messages
    ]


# ── WebSocket ─────────────────────────────────────────────────────────────────

@ws_router.websocket("/ws/chat/{channel_id}")
async def ws_chat(websocket: WebSocket, channel_id: str):
    import asyncio as _asyncio
    await websocket.accept()

    # Auth handshake: first message must be {"type": "auth", "token": "..."}
    try:
        auth_data = await _asyncio.wait_for(websocket.receive_json(), timeout=15.0)
    except (_asyncio.TimeoutError, Exception):
        await websocket.close(code=1008)
        return

    from app.config import settings as _settings
    if auth_data.get("type") != "auth" or auth_data.get("token") != _settings.auth_token:
        await websocket.close(code=1008)
        return

    # Register this connection for multi-device broadcast
    _connections.setdefault(channel_id, set()).add(websocket)

    # Use a fresh DB session for the WS lifetime (via module ref so tests can patch it)
    async with _db_module.async_session_factory() as db:
        result = await db.execute(select(Channel).where(Channel.id == channel_id))
        channel = result.scalar_one_or_none()
        if not channel:
            await websocket.send_json({"type": "error", "message": "Channel not found"})
            await websocket.close()
            _connections.get(channel_id, set()).discard(websocket)
            return

        # Send last 50 messages; tell client if older messages exist
        msgs_result = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id)
            .order_by(Message.created_at.desc())
            .limit(51)
        )
        all_recent = msgs_result.scalars().all()
        has_more = len(all_recent) > 50
        history = list(reversed(all_recent[:50]))
        for m in history:
            await websocket.send_json({"type": "history", "role": m.role, "content": m.content, "id": m.id})
        oldest_id = history[0].id if history else None
        await websocket.send_json({"type": "history_done", "has_more": has_more, "oldest_id": oldest_id})

        try:
            while True:
                data = await websocket.receive_json()
                user_text = data.get("message", "").strip()
                if not user_text:
                    continue

                # Persist user message; send to originator and broadcast to other devices
                user_msg = Message(channel_id=channel_id, role="user", content=user_text)
                db.add(user_msg)
                await db.commit()
                await db.refresh(user_msg)
                await websocket.send_json({"type": "user", "content": user_text, "id": user_msg.id})
                await _broadcast(channel_id, {"type": "user", "content": user_text, "id": user_msg.id}, exclude=websocket)

                # Stream opencode response — support cancellation
                await _broadcast(channel_id, {"type": "assistant_start"})
                response_parts: list[str] = []
                cancel_event = _asyncio.Event()
                cancelled = False

                async def _do_stream() -> None:
                    async for chunk, sid, _raw in stream_opencode(
                        user_text,
                        session_id=channel.opencode_session_id,
                        working_dir=channel.working_dir,
                        cancel=cancel_event,
                    ):
                        if sid and channel.opencode_session_id != sid:
                            channel.opencode_session_id = sid
                            await db.commit()
                        if chunk:
                            response_parts.append(chunk)
                            await _broadcast(channel_id, {"type": "chunk", "content": chunk})

                stream_task = _asyncio.create_task(_do_stream())

                # While streaming, listen for a cancel message from this client
                while not stream_task.done():
                    try:
                        incoming = await _asyncio.wait_for(websocket.receive_json(), timeout=0.2)
                        if incoming.get("type") == "cancel":
                            cancel_event.set()
                            cancelled = True
                    except _asyncio.TimeoutError:
                        pass
                    except Exception:
                        cancel_event.set()
                        break

                stream_error: str | None = None
                try:
                    await stream_task
                except RuntimeError as e:
                    stream_error = str(e)
                except _asyncio.CancelledError:
                    pass

                if stream_error:
                    await _broadcast(channel_id, {"type": "error", "message": stream_error})

                full_response = "".join(response_parts)
                if full_response:
                    asst_msg = Message(channel_id=channel_id, role="assistant", content=full_response)
                    db.add(asst_msg)
                    await db.commit()
                    await db.refresh(asst_msg)
                    await _broadcast(channel_id, {"type": "assistant_end", "id": asst_msg.id, "cancelled": cancelled})
                else:
                    await _broadcast(channel_id, {"type": "assistant_end", "id": None, "cancelled": cancelled})

        except WebSocketDisconnect:
            pass
        finally:
            _connections.get(channel_id, set()).discard(websocket)
