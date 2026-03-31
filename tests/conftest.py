import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from starlette.testclient import TestClient

from app.database import Base, get_db
from app.config import settings

TEST_TOKEN = "test-token-123"

# Override auth token for tests
settings.auth_token = TEST_TOKEN


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        from app import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def sync_client():
    """Synchronous TestClient for WebSocket tests. Uses its own in-memory DB."""
    import asyncio
    from app.main import app
    from app.database import async_session_factory as _orig_factory

    # Build a fresh in-memory engine + run migrations synchronously
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            from app import models  # noqa: F401
            await conn.run_sync(Base.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(setup())

    # Patch async_session_factory used inside the WS handler
    import app.routers.chat as chat_module
    original_factory = chat_module.async_session_factory if hasattr(chat_module, "async_session_factory") else None

    # Inject the test session factory into the WS handler module
    import app.database as db_module
    orig_engine = db_module.engine
    orig_factory = db_module.async_session_factory
    db_module.engine = engine
    db_module.async_session_factory = session_factory

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.shutdown = MagicMock()
    mock_scheduler.get_job = MagicMock(return_value=None)
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.remove_job = MagicMock()

    with patch("app.services.scheduler.scheduler", mock_scheduler), \
         patch("app.services.scheduler.load_all_tasks", return_value=None):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()
    db_module.engine = orig_engine
    db_module.async_session_factory = orig_factory
    asyncio.get_event_loop().run_until_complete(engine.dispose())
