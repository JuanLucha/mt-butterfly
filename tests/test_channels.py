import pytest
from tests.conftest import TEST_TOKEN

T = {"t": TEST_TOKEN}


@pytest.mark.asyncio
async def test_list_channels_empty(client):
    resp = await client.get("/api/channels", params=T)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_channel(client):
    resp = await client.post("/api/channels", params=T, json={"name": "general"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "general"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_channel_with_working_dir(client):
    resp = await client.post("/api/channels", params=T, json={"name": "project", "working_dir": "/tmp/proj"})
    assert resp.status_code == 201
    assert resp.json()["working_dir"] == "/tmp/proj"


@pytest.mark.asyncio
async def test_list_channels_returns_created(client):
    await client.post("/api/channels", params=T, json={"name": "ch1"})
    await client.post("/api/channels", params=T, json={"name": "ch2"})
    resp = await client.get("/api/channels", params=T)
    names = [c["name"] for c in resp.json()]
    assert "ch1" in names
    assert "ch2" in names


@pytest.mark.asyncio
async def test_delete_channel(client):
    create = await client.post("/api/channels", params=T, json={"name": "to-delete"})
    channel_id = create.json()["id"]

    resp = await client.delete(f"/api/channels/{channel_id}", params=T)
    assert resp.status_code == 204

    resp = await client.get("/api/channels", params=T)
    ids = [c["id"] for c in resp.json()]
    assert channel_id not in ids


@pytest.mark.asyncio
async def test_delete_channel_not_found(client):
    resp = await client.delete("/api/channels/nonexistent", params=T)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_channel_removes_messages(client):
    create = await client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]

    # Verify messages endpoint works before delete
    msgs = await client.get(f"/api/channels/{channel_id}/messages", params=T)
    assert msgs.status_code == 200

    await client.delete(f"/api/channels/{channel_id}", params=T)

    # After delete, messages endpoint returns 404
    msgs = await client.get(f"/api/channels/{channel_id}/messages", params=T)
    assert msgs.status_code == 404


@pytest.mark.asyncio
async def test_get_messages_empty(client):
    create = await client.post("/api/channels", params=T, json={"name": "ch"})
    channel_id = create.json()["id"]
    resp = await client.get(f"/api/channels/{channel_id}/messages", params=T)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_messages_not_found(client):
    resp = await client.get("/api/channels/nonexistent/messages", params=T)
    assert resp.status_code == 404
