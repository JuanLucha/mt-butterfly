import logging
import logging.handlers
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from platformdirs import user_log_dir

from app.database import init_db
from app.config import settings


def _configure_logging() -> None:
    log_dir = Path(user_log_dir("mt-butterfly", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "mt-butterfly.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
    )


_configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auth_token == "dev-token":
        import sys
        print(
            "\n⚠  WARNING: AUTH_TOKEN is the insecure default 'dev-token'."
            " Set AUTH_TOKEN in your config before exposing this service.\n",
            file=sys.stderr,
        )
    await init_db()
    Path(settings.workspaces_dir).mkdir(parents=True, exist_ok=True)
    from app.services.scheduler import scheduler, load_all_tasks

    await load_all_tasks()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="mt-butterfly", lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _asset_version() -> str:
    static = BASE_DIR / "static"
    mtimes = [p.stat().st_mtime for p in static.rglob("*") if p.is_file()]
    return str(int(max(mtimes))) if mtimes else "1"


templates.env.globals["asset_v"] = _asset_version()


# Import routers after app is created to avoid circular imports
from app.routers import chat, tasks  # noqa: E402

app.include_router(chat.router)
app.include_router(chat.ws_router)
app.include_router(tasks.router)


@app.get("/health")
async def health():
    from sqlalchemy import text
    from app.database import async_session_factory
    from app.services.scheduler import scheduler

    db_ok = False
    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    scheduler_ok = scheduler.running

    status = "ok" if (db_ok and scheduler_ok) else "degraded"
    return {"status": status, "db": db_ok, "scheduler": scheduler_ok}
