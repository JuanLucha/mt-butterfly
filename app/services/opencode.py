import asyncio
import json
from collections.abc import AsyncIterator
from app.config import settings


async def stream_opencode(
    message: str,
    session_id: str | None = None,
    working_dir: str | None = None,
) -> AsyncIterator[tuple[str, str | None]]:
    """
    Yields (chunk_text, session_id_or_None) as opencode produces output.
    session_id is yielded once on the first event that contains it.
    On error raises RuntimeError.
    """
    cmd = [settings.opencode_path, "run", message, "--format", "json"]
    if session_id:
        cmd += ["--session", session_id]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )

    discovered_session_id: str | None = None

    async for raw_line in proc.stdout:
        line = raw_line.decode().strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Extract session ID from any event
        if discovered_session_id is None:
            sid = event.get("sessionID")
            if sid:
                discovered_session_id = sid
                yield ("", discovered_session_id)

        if event.get("type") == "text":
            text = event.get("part", {}).get("text", "")
            if text:
                yield (text, None)

    await proc.wait()

    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        raise RuntimeError(stderr.decode().strip() or f"opencode exited with code {proc.returncode}")


async def run_opencode(
    message: str,
    session_id: str | None = None,
    working_dir: str | None = None,
) -> tuple[str, str | None]:
    """
    Runs opencode and returns (full_response_text, session_id).
    Use stream_opencode for streaming to WebSocket.
    """
    parts: list[str] = []
    found_session_id = session_id

    async for chunk, sid in stream_opencode(message, session_id, working_dir):
        if sid:
            found_session_id = sid
        if chunk:
            parts.append(chunk)

    return "".join(parts), found_session_id
