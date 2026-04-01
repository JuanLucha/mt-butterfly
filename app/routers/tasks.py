from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_token
from app.database import get_db
from app.models import Task, TaskRun
from app.services.scheduler import schedule_task, unschedule_task
from app.services.opencode import run_opencode
from app.tools.gmail import send_gmail

router = APIRouter(dependencies=[Depends(verify_token)])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ── HTML page ─────────────────────────────────────────────────────────────────

@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html")


# ── Schemas ───────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    name: str
    prompt: str
    hour: int
    minute: int = 0
    days_of_week: str = "mon,tue,wed,thu,fri"
    email_to: str | None = None
    enabled: bool = True

    @field_validator("hour")
    @classmethod
    def validate_hour(cls, v):
        if not 0 <= v <= 23:
            raise ValueError("hour must be 0–23")
        return v

    @field_validator("minute")
    @classmethod
    def validate_minute(cls, v):
        if not 0 <= v <= 59:
            raise ValueError("minute must be 0–59")
        return v


class TaskUpdate(TaskCreate):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _task_with_last_run(task: Task, db: AsyncSession) -> dict:
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    return {
        "id": task.id,
        "name": task.name,
        "prompt": task.prompt,
        "hour": task.hour,
        "minute": task.minute,
        "days_of_week": task.days_of_week,
        "working_dir": task.working_dir,
        "email_to": task.email_to,
        "enabled": task.enabled,
        "created_at": task.created_at,
        "last_run": {
            "id": last.id,
            "started_at": last.started_at,
            "completed_at": last.completed_at,
            "status": last.status,
        } if last else None,
    }


def _ensure_workspace(task: Task) -> None:
    """Create workspace dir for task from WORKSPACES_DIR + task name slug."""
    from app.config import settings
    import json
    import re
    if not settings.workspaces_dir:
        raise ValueError("WORKSPACES_DIR not configured")
    slug = re.sub(r"[^\w-]", "-", task.name.lower()).strip("-") or task.id
    workspace = Path(settings.workspaces_dir) / slug
    workspace.mkdir(parents=True, exist_ok=True)
    task.working_dir = str(workspace)

    # Allow opencode to operate without interactive permission prompts
    opencode_cfg = workspace / "opencode.json"
    if not opencode_cfg.exists():
        opencode_cfg.write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "permission": {"read": "allow", "write": "allow", "bash": "allow"},
        }, indent=2))

    # Write actual credentials so opencode can use them if needed
    env_file = workspace / ".env"
    env_lines = [
        f"GMAIL_USER={settings.gmail_user}",
        f"GMAIL_APP_PASSWORD={settings.gmail_app_password}",
    ]
    env_file.write_text("\n".join(env_lines) + "\n")


# ── REST ──────────────────────────────────────────────────────────────────────

@router.get("/api/tasks")
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(Task.created_at))
    tasks = result.scalars().all()
    return [await _task_with_last_run(t, db) for t in tasks]


@router.post("/api/tasks", status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    task = Task(**body.model_dump())
    _ensure_workspace(task)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    if task.enabled:
        schedule_task(task)
    return await _task_with_last_run(task, db)


@router.put("/api/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in body.model_dump().items():
        setattr(task, field, value)
    _ensure_workspace(task)
    await db.commit()
    await db.refresh(task)
    unschedule_task(task_id)
    if task.enabled:
        schedule_task(task)
    return await _task_with_last_run(task, db)


@router.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    unschedule_task(task_id)
    await db.delete(task)
    await db.commit()


@router.post("/api/tasks/{task_id}/run", status_code=202)
async def run_task_now(task_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.services.scheduler import _run_task
    background_tasks.add_task(_run_task, task_id)
    return {"status": "triggered"}


@router.get("/api/tasks/{task_id}/runs")
async def list_task_runs(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    result = await db.execute(
        select(TaskRun)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.started_at.desc())
    )
    runs = result.scalars().all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "status": r.status,
            "output": r.output,
        }
        for r in runs
    ]


@router.get("/api/tasks/runs/{run_id}")
async def get_task_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TaskRun).where(TaskRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "task_id": run.task_id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "status": run.status,
        "output": run.output,
    }
