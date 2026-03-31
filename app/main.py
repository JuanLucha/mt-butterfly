from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.database import init_db
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.include_router(tasks.router)
