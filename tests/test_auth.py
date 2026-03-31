import pytest
from tests.conftest import TEST_TOKEN


@pytest.mark.asyncio
async def test_no_token_returns_401(client):
    resp = await client.get("/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_returns_401(client):
    resp = await client.get("/", params={"t": "wrong-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_correct_token_returns_200(client):
    resp = await client.get("/", params={"t": TEST_TOKEN})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_tasks_page_no_token_returns_401(client):
    resp = await client.get("/tasks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tasks_page_correct_token_returns_200(client):
    resp = await client.get("/tasks", params={"t": TEST_TOKEN})
    assert resp.status_code == 200
