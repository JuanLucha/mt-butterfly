import pytest
from unittest.mock import patch, AsyncMock
from tests.conftest import TEST_TOKEN

T = {"t": TEST_TOKEN}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_empty(client):
    resp = await client.get("/api/tasks", params=T)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_task(client):
    with patch("app.routers.tasks.schedule_task"):
        resp = await client.post("/api/tasks", params=T, json={
            "name": "Daily report", "prompt": "Summarize the project", "hour": 9
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Daily report"
    assert data["hour"] == 9
    assert data["minute"] == 0
    assert data["enabled"] is True
    assert data["last_run"] is None


@pytest.mark.asyncio
async def test_create_task_validates_hour(client):
    resp = await client.post("/api/tasks", params=T, json={
        "name": "bad", "prompt": "x", "hour": 25
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_validates_minute(client):
    resp = await client.post("/api/tasks", params=T, json={
        "name": "bad", "prompt": "x", "hour": 9, "minute": 60
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_task(client):
    with patch("app.routers.tasks.schedule_task"), patch("app.routers.tasks.unschedule_task"):
        create = await client.post("/api/tasks", params=T, json={
            "name": "Old name", "prompt": "old prompt", "hour": 8
        })
        task_id = create.json()["id"]

        resp = await client.put(f"/api/tasks/{task_id}", params=T, json={
            "name": "New name", "prompt": "new prompt", "hour": 10, "minute": 30,
            "days_of_week": "mon,wed,fri", "enabled": True
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New name"
    assert data["hour"] == 10
    assert data["days_of_week"] == "mon,wed,fri"


@pytest.mark.asyncio
async def test_update_task_not_found(client):
    with patch("app.routers.tasks.unschedule_task"):
        resp = await client.put("/api/tasks/nonexistent", params=T, json={
            "name": "x", "prompt": "y", "hour": 9
        })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_task(client):
    with patch("app.routers.tasks.schedule_task"), patch("app.routers.tasks.unschedule_task"):
        create = await client.post("/api/tasks", params=T, json={
            "name": "to delete", "prompt": "x", "hour": 9
        })
        task_id = create.json()["id"]
        resp = await client.delete(f"/api/tasks/{task_id}", params=T)
    assert resp.status_code == 204

    resp = await client.get("/api/tasks", params=T)
    assert all(t["id"] != task_id for t in resp.json())


@pytest.mark.asyncio
async def test_delete_task_not_found(client):
    with patch("app.routers.tasks.unschedule_task"):
        resp = await client.delete("/api/tasks/nonexistent", params=T)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_disabled_task_not_scheduled(client):
    with patch("app.routers.tasks.schedule_task") as mock_schedule:
        await client.post("/api/tasks", params=T, json={
            "name": "disabled", "prompt": "x", "hour": 9, "enabled": False
        })
    mock_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_run_task_now(client):
    with patch("app.routers.tasks.schedule_task"):
        create = await client.post("/api/tasks", params=T, json={
            "name": "manual", "prompt": "do it", "hour": 9
        })
        task_id = create.json()["id"]

    with patch("app.services.scheduler._run_task", new_callable=AsyncMock) as mock_run:
        resp = await client.post(f"/api/tasks/{task_id}/run", params=T)
    assert resp.status_code == 202
    assert resp.json()["status"] == "triggered"


@pytest.mark.asyncio
async def test_run_task_now_not_found(client):
    resp = await client.post("/api/tasks/nonexistent/run", params=T)
    assert resp.status_code == 404


# ── Scheduler execution ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_task_executes_opencode_and_saves_run():
    from app.services.scheduler import _run_task
    from app.database import Base, async_session_factory
    from app.models import Task, TaskRun
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    import app.database as db_module

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        from app import models  # noqa
        await conn.run_sync(Base.metadata.create_all)

    orig_sf = db_module.async_session_factory
    db_module.async_session_factory = sf

    try:
        async with sf() as db:
            task = Task(name="test", prompt="hello", hour=9, enabled=True, working_dir="/tmp/test-task")
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        async def mock_stream(*a, **kw):
            yield ("Task done!", None, '{"type":"text","part":{"text":"Task done!"}}')

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream):
            with patch("app.tools.gmail.send_gmail", new_callable=AsyncMock):
                await _run_task(task_id)

        async with sf() as db:
            runs = await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))
            run = runs.scalar_one()
            assert run.status == "success"
            assert '{"type":"text"' in run.output
            assert run.completed_at is not None
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_task_sends_email_on_completion():
    from app.services.scheduler import _run_task
    from app.database import Base
    from app.models import Task
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.database as db_module

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        from app import models  # noqa
        await conn.run_sync(Base.metadata.create_all)

    orig_sf = db_module.async_session_factory
    db_module.async_session_factory = sf

    try:
        async with sf() as db:
            task = Task(name="email-test", prompt="do it", hour=9,
                        enabled=True, email_to="a@b.com", working_dir="/tmp/test-email")
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        async def mock_stream(*a, **kw):
            yield ("output text", None, '{"type":"text","part":{"text":"output text"}}')

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream):
            with patch("app.tools.gmail.send_gmail", new_callable=AsyncMock) as mock_mail:
                await _run_task(task_id)

        mock_mail.assert_called_once()
        call_args = mock_mail.call_args
        assert "a@b.com" in call_args[0][0]
        assert "email-test" in call_args[0][1]
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()
