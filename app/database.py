from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


async def init_db():
    from pathlib import Path
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if not db_path.startswith(":"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        from app import models  # noqa: F401 — ensure models are registered
        await conn.run_sync(Base.metadata.create_all)
