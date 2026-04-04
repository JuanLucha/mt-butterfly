import json
import logging
import asyncio
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, UTC, timedelta
from app.config import settings

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _load_skills() -> str:
    """Load all skill .md files from app/skills/ and return them concatenated."""
    if not _SKILLS_DIR.exists():
        return ""
    parts = []
    for skill_file in sorted(_SKILLS_DIR.glob("*.md")):
        parts.append(skill_file.read_text())
    return "\n\n---\n\n".join(parts)


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# 2.3 — limit concurrent task executions
_task_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _task_semaphore
    if _task_semaphore is None:
        _task_semaphore = asyncio.Semaphore(settings.task_max_concurrent)
    return _task_semaphore


def _job_id(task_id: str) -> str:
    return f"task_{task_id}"


def _check_output_for_violations(raw_lines: list[str]) -> bool:
    """
    2.1 — Scan JSONL output for signs the LLM ignored the CLI tools:
    - pip install calls
    - using smtplib or requests directly
    - writing/creating .py files
    Returns True if suspicious activity was found.
    """
    suspicious_patterns = [
        "pip install",
        "smtplib",
        "import requests",
        "import smtplib",
        "_io.open",  # writing .py files directly
    ]
    for line in raw_lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type not in ("tool_use", "tool_result"):
            continue
        part = event.get("part", {})
        # Check input (the command being run)
        tool_input = part.get("input", {})
        command = ""
        if isinstance(tool_input, dict):
            command = tool_input.get("command", "") or tool_input.get("content", "")
        elif isinstance(tool_input, str):
            command = tool_input
        # Also check state output
        state = part.get("state", {})
        output = state.get("output", "") or ""
        text_to_check = f"{command} {output}"
        for pattern in suspicious_patterns:
            if pattern in text_to_check:
                logger.warning(
                    f"Violation detected in task output: pattern '{pattern}' found"
                )
                return True
    return False


async def _run_task(task_id: str) -> None:
    """Execute a task: run opencode, save TaskRun, send email."""
    from app.database import async_session_factory
    from app.models import Task, TaskRun
    from app.services.opencode import stream_opencode
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

    run_id = run.id

    # 2.3 — acquire semaphore before running
    async with _get_semaphore():
        async with async_session_factory() as db:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            result2 = await db.execute(select(TaskRun).where(TaskRun.id == run_id))
            run = result2.scalar_one()

            try:
                email_instruction = (
                    f"Default recipient for this task: {task.email_to}\n"
                    f'  mt-butterfly-gmail --to {task.email_to} --subject "<subject>" --body-file <path>\n'
                    if task.email_to
                    else "(no recipient configured for this task — skip email)\n"
                )
                skills_docs = _load_skills()
                constrained_prompt = (
                    f"You MUST work only inside the directory: {task.working_dir}\n\n"
                    f"## STRICT RULES — follow these exactly\n\n"
                    f"1. Do NOT write Python scripts or any custom code to accomplish the task.\n"
                    f"2. Do NOT use pip, install packages, or libraries.\n"
                    f"3. Do NOT use smtplib, requests, or any other library to send emails or fetch data.\n"
                    f"4. You MUST use ONLY the CLI tools documented below for all operations.\n"
                    f"5. Do NOT set, export, or look up credentials.\n"
                    f'6. If the user specifies a time window (e.g., "last 24 hours", "today"), you MUST respect that exact time window and NOT expand or change it.\n\n'
                    f"## Available CLI tools\n\n"
                    f"{skills_docs}\n\n"
                    f"## Email recipient\n\n"
                    f"{email_instruction}\n"
                    f"When generating an HTML email body, follow this structure and style:\n"
                    f"  - Title at the top\n"
                    f"  - For each channel: channel name, then for each video: video title, bullet-point list of key points, an 'Actionables' box with extracted action items, and a link to the video\n"
                    f"  - Use high-contrast colours: dark backgrounds (#1a1a2e or similar) with light text (#f0f0f0), accent colours with sufficient contrast ratio. Avoid low-contrast combos like blue text on grey.\n\n"
                    f"## Task\n\n"
                    f"{task.prompt}"
                )
                logger.info(f"Running opencode in {task.working_dir}")
                logger.info(f"Prompt: {constrained_prompt[:200]}...")

                timeout_seconds = task.timeout_minutes * 60
                raw_lines: list[str] = []
                text_parts: list[str] = []

                # 2.2 — wrap stream in timeout
                async def _collect():
                    async for chunk, _sid, raw in stream_opencode(
                        constrained_prompt, working_dir=task.working_dir
                    ):
                        if raw:
                            raw_lines.append(raw)
                        if chunk:
                            text_parts.append(chunk)

                await asyncio.wait_for(_collect(), timeout=timeout_seconds)

                output = "\n".join(raw_lines)

                # 2.1 — post-execution verification
                if _check_output_for_violations(raw_lines):
                    run.status = "needs_review"
                    logger.warning(
                        f"Task {task_id} completed but needs review (LLM may have bypassed CLI tools)"
                    )
                else:
                    run.status = "success"

                logger.info(f"Opencode raw lines: {len(raw_lines)}")

            except asyncio.TimeoutError:
                logger.error(
                    f"Task {task_id} timed out after {task.timeout_minutes} minutes"
                )
                output = f"Task timed out after {task.timeout_minutes} minutes"
                run.status = "timeout"
            except Exception as e:
                logger.exception(f"Task {task_id} failed: {e}")
                output = str(e)
                run.status = "error"

            run.output = output
            run.completed_at = datetime.now(UTC)
            await db.commit()


async def _cleanup_old_runs() -> None:
    """2.4 — Delete TaskRuns older than the configured retention period."""
    from app.database import async_session_factory
    from app.models import TaskRun
    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=settings.task_run_retention_days)
    async with async_session_factory() as db:
        result = await db.execute(delete(TaskRun).where(TaskRun.started_at < cutoff))
        await db.commit()
        deleted = result.rowcount
        if deleted:
            logger.info(
                f"Retention cleanup: deleted {deleted} TaskRun(s) older than {settings.task_run_retention_days} days"
            )


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

    # 2.4 — register daily retention cleanup at 3am
    scheduler.add_job(
        _cleanup_old_runs,
        CronTrigger(hour=3, minute=0),
        id="cleanup_old_runs",
        replace_existing=True,
    )
