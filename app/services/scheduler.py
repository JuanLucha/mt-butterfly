import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, UTC

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


def _job_id(task_id: str) -> str:
    return f"task_{task_id}"


async def _run_task(task_id: str) -> None:
    """Execute a task: run opencode, save TaskRun, send email."""
    from app.database import async_session_factory
    from app.models import Task, TaskRun
    from app.services.opencode import run_opencode
    from sqlalchemy import select

    logger.info(f"Starting task {task_id}")

    async with async_session_factory() as db:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task or not task.enabled:
            logger.warning(f"Task {task_id} not found or disabled")
            return

        run = TaskRun(task_id=task_id, started_at=datetime.now(UTC), status="running")
        db.add(run)
        await db.commit()
        await db.refresh(run)

        try:
            from app.services.opencode import stream_opencode
            email_instruction = (
                f"  mt-butterfly-gmail --to {task.email_to} --subject \"<subject>\" --body-file <path>\n"
                if task.email_to else
                "  (no recipient configured for this task — skip email)\n"
            )
            constrained_prompt = (
                f"You MUST work only inside the directory: {task.working_dir}\n\n"
                f"## STRICT RULES — follow these exactly\n\n"
                f"1. Do NOT write Python scripts or any custom code to accomplish the task.\n"
                f"2. Do NOT use pip, install packages, or import libraries.\n"
                f"3. Do NOT use smtplib, requests, or any other library to send emails or fetch data.\n"
                f"4. You MUST use ONLY the CLI tools listed below for all operations.\n\n"
                f"## CLI tools (use these and nothing else)\n\n"
                f"To send an email via Gmail (credentials are pre-configured):\n"
                f"{email_instruction}"
                f"  mt-butterfly-gmail --to <address> --subject \"<subject>\" --body \"<body>\"\n"
                f"  mt-butterfly-gmail --to <address> --subject \"<subject>\" --body-file <path.html> --html\n"
                f"  Use --html when the body is an HTML file so it renders correctly in email clients.\n\n"
                f"When generating an HTML email body, follow this structure and style:\n"
                f"  - Title at the top\n"
                f"  - For each channel: channel name, then for each video: video title, bullet-point list of key points, an 'Actionables' box with extracted action items, and a link to the video\n"
                f"  - Use high-contrast colours: dark backgrounds (#1a1a2e or similar) with light text (#f0f0f0), accent colours with sufficient contrast ratio. Avoid low-contrast combos like blue text on grey.\n\n"
                f"To download YouTube transcripts:\n"
                f"  mt-butterfly-youtube <video_url_or_id> [--format json] [--output-dir <dir>] [--print]\n"
                f"  Do NOT pass --lang. The tool auto-selects the transcript language.\n\n"
                f"## Task\n\n"
                f"{task.prompt}"
            )
            logger.info(f"Running opencode in {task.working_dir}")
            logger.info(f"Prompt: {constrained_prompt[:200]}...")
            raw_lines: list[str] = []
            text_parts: list[str] = []
            async for chunk, _sid, raw in stream_opencode(
                constrained_prompt, working_dir=task.working_dir
            ):
                if raw:
                    raw_lines.append(raw)
                if chunk:
                    text_parts.append(chunk)
            output = "\n".join(raw_lines)
            output_text = "".join(text_parts)
            logger.info(f"Opencode raw lines: {len(raw_lines)}")
            run.status = "success"
        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            output = str(e)
            output_text = output
            run.status = "error"

        run.output = output
        run.completed_at = datetime.now(UTC)
        await db.commit()


def schedule_task(task) -> None:
    days = task.days_of_week or "mon,tue,wed,thu,fri"
    trigger = CronTrigger(hour=task.hour, minute=task.minute, day_of_week=days)
    job_id = _job_id(task.id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        _run_task, trigger, args=[task.id], id=job_id, replace_existing=True
    )


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
