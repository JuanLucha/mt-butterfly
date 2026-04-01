import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.opencode import run_opencode, stream_opencode
from app.config import settings


def make_mock_proc(stdout_lines: list[str], returncode: int = 0):
    """Build a mock subprocess with the given stdout lines."""
    async def mock_readline():
        for line in stdout_lines:
            yield line.encode()

    proc = MagicMock()
    proc.stdout.__aiter__ = lambda self: mock_readline()
    proc.returncode = returncode

    async def mock_wait():
        pass
    proc.wait = mock_wait

    async def mock_read():
        return b"some error"
    proc.stderr.read = mock_read

    return proc


EVENTS = [
    json.dumps({"type": "step_start", "sessionID": "ses_abc123", "part": {}}),
    json.dumps({"type": "text", "sessionID": "ses_abc123", "part": {"text": "Hello "}}),
    json.dumps({"type": "text", "sessionID": "ses_abc123", "part": {"text": "world!"}}),
    json.dumps({"type": "step_finish", "sessionID": "ses_abc123", "part": {"reason": "stop"}}),
]


@pytest.mark.asyncio
async def test_run_opencode_returns_text_and_session_id():
    proc = make_mock_proc(EVENTS)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        text, sid = await run_opencode("say hello")
    assert text == "Hello world!"
    assert sid == "ses_abc123"


@pytest.mark.asyncio
async def test_run_opencode_uses_existing_session_id():
    proc = make_mock_proc(EVENTS)
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_opencode("follow up", session_id="ses_existing")
    cmd = mock_exec.call_args[0]
    assert "--session" in cmd
    assert "ses_existing" in cmd


@pytest.mark.asyncio
async def test_run_opencode_no_session_arg_without_session_id():
    proc = make_mock_proc(EVENTS)
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_opencode("first message")
    cmd = mock_exec.call_args[0]
    assert "--session" not in cmd


@pytest.mark.asyncio
async def test_run_opencode_uses_working_dir():
    proc = make_mock_proc(EVENTS)
    with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        await run_opencode("hi", working_dir="/tmp/myproject")
    kwargs = mock_exec.call_args[1]
    assert kwargs.get("cwd") == "/tmp/myproject"


@pytest.mark.asyncio
async def test_run_opencode_raises_on_nonzero_exit():
    proc = make_mock_proc([], returncode=1)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(RuntimeError):
            await run_opencode("fail")


@pytest.mark.asyncio
async def test_stream_opencode_yields_chunks():
    proc = make_mock_proc(EVENTS)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        chunks = []
        async for chunk, sid, raw in stream_opencode("say hello"):
            chunks.append((chunk, sid, raw))

    # First yield: empty chunk with session_id
    assert chunks[0][:2] == ("", "ses_abc123")
    # Rest: text chunks
    texts = [c for c, s, r in chunks if c]
    assert texts == ["Hello ", "world!"]


@pytest.mark.asyncio
async def test_run_opencode_ignores_malformed_json():
    lines = [
        "not json",
        json.dumps({"type": "step_start", "sessionID": "ses_xyz", "part": {}}),
        "{ broken",
        json.dumps({"type": "text", "sessionID": "ses_xyz", "part": {"text": "ok"}}),
        json.dumps({"type": "step_finish", "sessionID": "ses_xyz", "part": {}}),
    ]
    proc = make_mock_proc(lines)
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        text, sid = await run_opencode("test")
    assert text == "ok"
    assert sid == "ses_xyz"
