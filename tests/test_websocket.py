import json
import pytest
from unittest.mock import patch
from tests.conftest import TEST_TOKEN

T = {"t": TEST_TOKEN}

MOCK_EVENTS = [
    ("", "ses_new123"),
    ("Hello ", None),
    ("there!", None),
]


async def mock_stream(*args, **kwargs):
    for chunk, sid in MOCK_EVENTS:
        yield chunk, sid


def test_websocket_rejects_without_token(sync_client):
    from starlette.testclient import WebSocketDenialResponse
    create = sync_client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]
    with pytest.raises(WebSocketDenialResponse) as exc_info:
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}") as ws:
            pass
    assert exc_info.value.status_code == 401


def test_websocket_accepts_with_token(sync_client):
    create = sync_client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]
    with patch("app.routers.chat.stream_opencode", side_effect=mock_stream):
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}?t={TEST_TOKEN}") as ws:
            ws.send_json({"message": "hi"})
            msgs = []
            for _ in range(10):
                msg = ws.receive_json()
                msgs.append(msg)
                if msg["type"] == "assistant_end":
                    break
            types = [m["type"] for m in msgs]
            assert "user" in types
            assert "assistant_start" in types
            assert "chunk" in types
            assert "assistant_end" in types


def test_websocket_streams_chunks(sync_client):
    create = sync_client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]
    with patch("app.routers.chat.stream_opencode", side_effect=mock_stream):
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}?t={TEST_TOKEN}") as ws:
            ws.send_json({"message": "hello"})
            chunks = []
            while True:
                msg = ws.receive_json()
                if msg["type"] == "chunk":
                    chunks.append(msg["content"])
                if msg["type"] == "assistant_end":
                    break
            assert "".join(chunks) == "Hello there!"


def test_websocket_persists_messages(sync_client):
    create = sync_client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]
    with patch("app.routers.chat.stream_opencode", side_effect=mock_stream):
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}?t={TEST_TOKEN}") as ws:
            ws.send_json({"message": "persist me"})
            while True:
                msg = ws.receive_json()
                if msg["type"] == "assistant_end":
                    break

    resp = sync_client.get(f"/api/channels/{channel_id}/messages", params=T)
    messages = resp.json()
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    contents = [m["content"] for m in messages]
    assert "persist me" in contents
    assert "Hello there!" in contents


def test_websocket_sends_history_on_connect(sync_client):
    create = sync_client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]

    # First session: send a message
    with patch("app.routers.chat.stream_opencode", side_effect=mock_stream):
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}?t={TEST_TOKEN}") as ws:
            ws.send_json({"message": "first"})
            while True:
                msg = ws.receive_json()
                if msg["type"] == "assistant_end":
                    break

    # Second connection: history messages should arrive before any new exchange
    with patch("app.routers.chat.stream_opencode", side_effect=mock_stream):
        with sync_client.websocket_connect(f"/ws/chat/{channel_id}?t={TEST_TOKEN}") as ws:
            ws.send_json({"message": "second"})
            all_msgs = []
            while True:
                msg = ws.receive_json()
                all_msgs.append(msg)
                if msg["type"] == "assistant_end":
                    break
            history = [m for m in all_msgs if m["type"] == "history"]
            assert len(history) == 2  # user + assistant from first session


def test_websocket_channel_not_found(sync_client):
    with sync_client.websocket_connect(f"/ws/chat/nonexistent?t={TEST_TOKEN}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
