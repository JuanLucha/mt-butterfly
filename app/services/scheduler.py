from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, UTC

scheduler = AsyncIOScheduler()


def _job_id(task_id: str) -> str:
    return f"task_{task_id}"


async def _run_task(task_id: str) -> None:
    """Execute a task: run opencode, save TaskRun, send email."""
    from app.database import async_session_factory
    from app.models import Task, TaskRun
    from app.services.opencode import run_opencode
    from app.services.email import send_gmail
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task or not task.enabled:
            return

        run = TaskRun(task_id=task_id, started_at=datetime.now(UTC), status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)

        try:
            constrained_prompt = f"You MUST work only inside the directory: {task.working_dir}\n\n{task.prompt}"
            output, _ = await run_opencode(constrained_prompt, working_dir=task.working_dir)
            run.status = "success"
        except Exception as e:
            output = str(e)
            run.status = "error"

        run.output = output
        run.completed_at = datetime.now(UTC)
        await db.commit()

    # Send email if configured
    if task.email_to and task.email_to.strip():
        recipients = [e.strip() for e in task.email_to.split(",") if e.strip()]
        subject = f"[mt-butterfly] Task '{task.name}' — {run.status}"
        body = f"Task: {task.name}\nStatus: {run.status}\nStarted: {run.started_at}\nFinished: {run.completed_at}\n\n--- Output ---\n\n{output}"
        try:
            await send_gmail(recipients, subject, body)
        except Exception:
            pass  # Don't fail the run if email fails


def schedule_task(task) -> None:
    days = task.days_of_week or "mon,tue,wed,thu,fri"
    trigger = CronTrigger(hour=task.hour, minute=task.minute, day_of_week=days)
    job_id = _job_id(task.id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(_run_task, trigger, args=[task.id], id=job_id, replace_existing=True)


def unschedule_task(task_id: str) -> None:
    job_id = _job_id(task_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def load_all_tasks() -> None:
    """Called on app startup to register all enabled tasks."""
    from app.database import async_session_factory
    from app.models import Task
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(select(Task).where(Task.enabled == True))  # noqa: E712
        for task in result.scalars().all():
            schedule_task(task)
