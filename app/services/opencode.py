import asyncio
import json
import logging
from collections.abc import AsyncIterator
from app.config import settings

logger = logging.getLogger(__name__)


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

    logger.info(f"Running command: {' '.join(cmd)}")
    logger.info(f"Working directory: {working_dir}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )

    discovered_session_id: str | None = None

    async for raw_line in proc.stdout:
        line = raw_line.decode().strip()
        logger.info(f"Received line: {line[:200] if line else 'EMPTY'}")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {line[:100]}")
            continue

        # Extract session ID from any event
        if discovered_session_id is None:
            sid = event.get("sessionID")
            if sid:
                discovered_session_id = sid
                yield ("", discovered_session_id)

        if event.get("type") == "text":
            text = event.get("part", {}).get("text", "")
            logger.info(f"Yielding text: {text[:100] if text else 'EMPTY'}")
            if text:
                yield (text, None)

    await proc.wait()
    logger.info(f"Process finished with return code: {proc.returncode}")

    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        err_msg = (
            stderr.decode().strip()
            if stderr
            else f"opencode exited with code {proc.returncode}"
        )
        logger.error(f"Opencode error: {err_msg}")
        raise RuntimeError(err_msg)


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
