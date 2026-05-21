import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from nexusflow.shared.models.database import (
    init_db,
    close_db,
    get_db,
    create_all_tables
)
import nexusflow.shared.models.database as db_module


@pytest.mark.asyncio
async def test_init_db_and_close_db():
    mock_engine = MagicMock()
    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_connect_ctx.__aexit__ = AsyncMock()
    mock_engine.connect.return_value = mock_connect_ctx
    mock_engine.dispose = AsyncMock()

    with patch("nexusflow.shared.models.database.create_async_engine", return_value=mock_engine) as mock_create_engine, \
         patch("nexusflow.shared.models.database.async_sessionmaker") as mock_sessionmaker:

        await init_db()

        mock_create_engine.assert_called_once()
        mock_sessionmaker.assert_called_once()
        mock_engine.connect.assert_called_once()

        mock_session_ctx = MagicMock()
        mock_session = MagicMock()
        mock_sessionmaker.return_value.return_value = mock_session_ctx

        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock()

        mock_begin_ctx = MagicMock()
        mock_begin_ctx.__aenter__ = AsyncMock()
        mock_begin_ctx.__aexit__ = AsyncMock()
        mock_session.begin.return_value = mock_begin_ctx

        async with get_db() as session:
            assert session == mock_session

        await close_db()
        mock_engine.dispose.assert_called_once()
        assert db_module._engine is None


@pytest.mark.asyncio
async def test_get_db_uninitialized():
    db_module._session_factory = None
    with pytest.raises(RuntimeError, match="Database not initialized"):
        async with get_db():
            pass


@pytest.mark.asyncio
async def test_create_all_tables():
    mock_engine = MagicMock()
    mock_begin_ctx = MagicMock()
    mock_begin_ctx.__aenter__ = AsyncMock()
    mock_begin_ctx.__aexit__ = AsyncMock()
    mock_engine.begin.return_value = mock_begin_ctx
    db_module._engine = mock_engine

    await create_all_tables()

    mock_engine.begin.assert_called_once()


@pytest.mark.asyncio
async def test_create_all_tables_uninitialized():
    db_module._engine = None
    with pytest.raises(RuntimeError, match="Database not initialized"):
        await create_all_tables()
