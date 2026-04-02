import asyncio
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

        # Email is sent by the LLM via the mt-butterfly-gmail CLI tool, not called
        # directly from Python. Verify the constrained prompt includes the recipient.
        captured_prompts = []

        async def mock_stream_capture(*a, **kw):
            captured_prompts.append(a[0] if a else kw.get("message", ""))
            yield ("output text", None, '{"type":"text","part":{"text":"output text"}}')

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream_capture):
            await _run_task(task_id)

        assert captured_prompts, "stream_opencode was not called"
        assert "a@b.com" in captured_prompts[0]
        assert "mt-butterfly-gmail" in captured_prompts[0]
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


# ── _ensure_workspace ─────────────────────────────────────────────────────────

def test_ensure_workspace_creates_directory(tmp_path, monkeypatch):
    from app.routers.tasks import _ensure_workspace
    from app.models import Task
    from app.config import settings

    monkeypatch.setattr(settings, "workspaces_dir", str(tmp_path))
    task = Task(name="My Task", prompt="x", hour=9)
    _ensure_workspace(task)

    workspace = tmp_path / "my-task"
    assert workspace.is_dir()
    assert task.working_dir == str(workspace)


def test_ensure_workspace_creates_opencode_json(tmp_path, monkeypatch):
    from app.routers.tasks import _ensure_workspace
    from app.models import Task
    from app.config import settings
    import json

    monkeypatch.setattr(settings, "workspaces_dir", str(tmp_path))
    task = Task(name="test-task", prompt="x", hour=9)
    _ensure_workspace(task)

    cfg = tmp_path / "test-task" / "opencode.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["permission"]["bash"] == "allow"
    assert data["permission"]["read"] == "allow"
    assert data["permission"]["write"] == "allow"


def test_ensure_workspace_slug_strips_special_chars(tmp_path, monkeypatch):
    from app.routers.tasks import _ensure_workspace
    from app.models import Task
    from app.config import settings

    monkeypatch.setattr(settings, "workspaces_dir", str(tmp_path))
    task = Task(name="My Task! 2024", prompt="x", hour=9)
    _ensure_workspace(task)

    workspace = tmp_path / "my-task--2024"
    assert workspace.is_dir()


def test_ensure_workspace_raises_without_workspaces_dir(monkeypatch):
    from app.routers.tasks import _ensure_workspace
    from app.models import Task
    from app.config import settings

    monkeypatch.setattr(settings, "workspaces_dir", None)
    task = Task(name="x", prompt="x", hour=9)
    with pytest.raises(ValueError, match="WORKSPACES_DIR"):
        _ensure_workspace(task)


def test_ensure_workspace_does_not_overwrite_existing_opencode_json(tmp_path, monkeypatch):
    from app.routers.tasks import _ensure_workspace
    from app.models import Task
    from app.config import settings

    monkeypatch.setattr(settings, "workspaces_dir", str(tmp_path))
    workspace = tmp_path / "my-task"
    workspace.mkdir()
    cfg = workspace / "opencode.json"
    cfg.write_text('{"custom": true}')

    task = Task(name="My Task", prompt="x", hour=9)
    _ensure_workspace(task)

    assert cfg.read_text() == '{"custom": true}'


# ── constrained_prompt content ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_constrained_prompt_contains_strict_rules():
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
            task = Task(name="t", prompt="do something", hour=9, enabled=True, working_dir="/tmp/t")
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        captured = []

        async def mock_stream(prompt, **kw):
            captured.append(prompt)
            yield ("done", None, '{"type":"text","part":{"text":"done"}}')

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream):
            await _run_task(task_id)

        assert captured
        p = captured[0]
        assert "Do NOT write Python scripts" in p
        assert "Do NOT use pip" in p
        assert "smtplib" in p
        assert "/tmp/t" in p
        assert "do something" in p
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


@pytest.mark.asyncio
async def test_constrained_prompt_no_email_message_when_no_email_to():
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
            task = Task(name="t", prompt="do something", hour=9, enabled=True,
                        working_dir="/tmp/t", email_to=None)
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        captured = []

        async def mock_stream(prompt, **kw):
            captured.append(prompt)
            yield ("done", None, '{"type":"text","part":{"text":"done"}}')

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream):
            await _run_task(task_id)

        assert "no recipient configured" in captured[0]
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


# ── _check_output_for_violations ──────────────────────────────────────────────

def test_check_output_no_violations():
    from app.services.scheduler import _check_output_for_violations

    lines = [
        '{"type":"tool_use","part":{"input":{"command":"mt-butterfly-gmail --to a@b.com"}}}',
        '{"type":"text","part":{"text":"done"}}',
    ]
    assert _check_output_for_violations(lines) is False


def test_check_output_detects_pip_install():
    from app.services.scheduler import _check_output_for_violations

    lines = [
        '{"type":"tool_use","part":{"input":{"command":"pip install requests"}}}',
    ]
    assert _check_output_for_violations(lines) is True


def test_check_output_detects_python_file_creation():
    from app.services.scheduler import _check_output_for_violations

    lines = [
        '{"type":"tool_use","part":{"input":{"command":"python send_email.py"}}}',
    ]
    assert _check_output_for_violations(lines) is True


def test_check_output_detects_smtplib_in_output():
    from app.services.scheduler import _check_output_for_violations

    lines = [
        '{"type":"tool_result","part":{"state":{"output":"import smtplib\\nsmtp = smtplib.SMTP(...)"}}}',
    ]
    assert _check_output_for_violations(lines) is True


def test_check_output_ignores_malformed_json():
    from app.services.scheduler import _check_output_for_violations

    lines = ["not-json", "{broken"]
    assert _check_output_for_violations(lines) is False


# ── Full flow: timeout and error ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_task_marks_timeout_status():
    from app.services.scheduler import _run_task
    from app.database import Base
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
            task = Task(name="t", prompt="do it", hour=9, enabled=True,
                        working_dir="/tmp/t", timeout_minutes=1)
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        async def slow_stream(*a, **kw):
            await asyncio.sleep(9999)
            yield ("done", None, '{}')

        with patch("app.services.opencode.stream_opencode", side_effect=slow_stream), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await _run_task(task_id)

        async with sf() as db:
            runs = await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))
            run = runs.scalar_one()
            assert run.status == "timeout"
            assert "timed out" in run.output
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_task_marks_error_status_on_exception():
    from app.services.scheduler import _run_task
    from app.database import Base
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
            task = Task(name="t", prompt="do it", hour=9, enabled=True, working_dir="/tmp/t")
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        async def failing_stream(*a, **kw):
            raise RuntimeError("opencode exploded")
            yield  # make it a generator

        with patch("app.services.opencode.stream_opencode", side_effect=failing_stream):
            await _run_task(task_id)

        async with sf() as db:
            runs = await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))
            run = runs.scalar_one()
            assert run.status == "error"
            assert "opencode exploded" in run.output
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_task_marks_needs_review_on_violation():
    from app.services.scheduler import _run_task
    from app.database import Base
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
            task = Task(name="t", prompt="do it", hour=9, enabled=True, working_dir="/tmp/t")
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

        violation_line = '{"type":"tool_use","part":{"input":{"command":"pip install requests"}}}'

        async def mock_stream(*a, **kw):
            yield ("done", None, violation_line)

        with patch("app.services.opencode.stream_opencode", side_effect=mock_stream):
            await _run_task(task_id)

        async with sf() as db:
            runs = await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))
            run = runs.scalar_one()
            assert run.status == "needs_review"
    finally:
        db_module.async_session_factory = orig_sf
        await engine.dispose()
