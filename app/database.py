from pathlib import Path
import asyncio

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


def _run_alembic_upgrade() -> None:
    """Run Alembic migrations synchronously (called from a thread executor).

    For databases created before Alembic was introduced (no alembic_version
    table), we stamp them as the initial revision so upgrade head is a no-op.
    """
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect

    alembic_cfg = Config()
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).parent / "migrations")
    )
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Detect existing databases that pre-date Alembic tracking and stamp them
    # so upgrade head doesn't try to re-create tables that already exist.
    # We use sqlite3 directly to avoid async/commit issues with the stamp command.
    sync_url = settings.database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    sync_engine = create_engine(sync_url)
    try:
        with sync_engine.connect() as conn:
            from sqlalchemy import text
            insp = inspect(sync_engine)
            has_version_table = insp.has_table("alembic_version")
            has_data = insp.has_table("channels")
            if has_version_table and has_data:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                already_tracked = row is not None
            else:
                already_tracked = False
    finally:
        sync_engine.dispose()

    if has_data and not already_tracked:
        import sqlite3
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            con.execute("INSERT OR IGNORE INTO alembic_version VALUES ('0001')")
            con.commit()
        finally:
            con.close()

    command.upgrade(alembic_cfg, "head")


async def init_db() -> None:
    # Ensure the database file directory exists before Alembic tries to connect.
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    if not db_path.startswith(":"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Run Alembic migrations in a thread so asyncio.run() inside env.py
    # can create its own event loop without conflicting with ours.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_alembic_upgrade)
