import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from app.config import settings

logger = logging.getLogger(__name__)


async def stream_opencode(
    message: str,
    session_id: str | None = None,
    working_dir: str | None = None,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[tuple[str, str | None, str | None]]:
    """
    Yields (chunk_text, session_id_or_None, raw_json_line_or_None).
    raw_json_line is the original JSON string for every parsed event.
    session_id is yielded once on the first event that contains it.
    On error raises RuntimeError.
    """
    cmd = [settings.opencode_path, "run", message, "--format", "json"]
    if session_id:
        cmd += ["--session", session_id]

    logger.info(f"Running command: {' '.join(cmd)}")
    logger.info(f"Working directory: {working_dir}")

    # Pass Gmail credentials as env vars so CLI tools can read them without a .env file on disk
    proc_env = os.environ.copy()
    if settings.gmail_user:
        proc_env["GMAIL_USER"] = settings.gmail_user
    if settings.gmail_app_password:
        proc_env["GMAIL_APP_PASSWORD"] = settings.gmail_app_password

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
        env=proc_env,
        limit=10 * 1024 * 1024,  # 10 MB — opencode lines can be very long
    )

    discovered_session_id: str | None = None

    async for raw_line in proc.stdout:
        if cancel and cancel.is_set():
            proc.kill()
            await proc.wait()
            return
        line = raw_line.decode().strip()
        logger.info(f"Received line: {line[:500] if line else 'EMPTY'}")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {line[:100]}")
            continue

        # Log full event structure
        logger.info(f"Full event keys: {list(event.keys())}")
        logger.info(f"Event part keys: {list(event.get('part', {}).keys())}")

        # Extract session ID from any event
        if discovered_session_id is None:
            sid = event.get("sessionID")
            if sid:
                discovered_session_id = sid
                yield ("", discovered_session_id, None)

        # Extract text from different event types
        event_type = event.get("type")
        text = None

        part = event.get("part", {})
        state = part.get("state", {})

        if event_type == "text":
            text = part.get("text", "")
        elif event_type == "message":
            content = part.get("content", "")
            if isinstance(content, list):
                text = "".join(
                    t.get("text", "") for t in content if isinstance(t, dict)
                )
            elif isinstance(content, str):
                text = content
        elif event_type == "tool_use" or event_type == "tool_result":
            # Extract from state - tools put output here
            state_output = state.get("output", "")
            state_error = state.get("error", "")

            if state_output:
                text = (
                    state_output if isinstance(state_output, str) else str(state_output)
                )
            elif state_error:
                text = f"ERROR: {state_error}"

        logger.info(
            f"Event type: {event_type}, extracted text: {text[:200] if text else 'EMPTY'}"
        )

        yield (text or "", None, line)

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

    async for chunk, sid, _raw in stream_opencode(message, session_id, working_dir):
        if sid:
            found_session_id = sid
        if chunk:
            parts.append(chunk)

    return "".join(parts), found_session_id
