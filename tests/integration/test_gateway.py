import pytest
import pytest_asyncio

try:
    from httpx import AsyncClient, ASGITransport
    from nexusflow.services.gateway.app import app
    from nexusflow.shared.models.database import init_db, close_db, create_all_tables
    from nexusflow.shared.queue.redis_streams import RedisConnectionPool
    INFRA_AVAILABLE = True
except Exception:
    INFRA_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not INFRA_AVAILABLE,
    reason="Integration tests require PostgreSQL and Redis",
)


async def _check_infra() -> bool:
    """Return False if PostgreSQL or Redis is unreachable."""
    try:
        import nexusflow.shared.models.database as db_module
        from nexusflow.shared.config.settings import get_settings
        settings = get_settings()

        import asyncpg
        conn = await asyncpg.connect(
            host=settings.database.host,
            port=settings.database.port,
            user=settings.database.user,
            password=settings.database.password,
            database=settings.database.db,
            timeout=2,
        )
        await conn.close()

        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis.url)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def setup_db():
    if not await _check_infra():
        pytest.skip("PostgreSQL or Redis not reachable")
    await init_db()
    await create_all_tables()
    yield
    await close_db()
    await RedisConnectionPool.close()


@pytest_asyncio.fixture
async def client(setup_db):
    from nexusflow.shared.queue.redis_streams import RedisConnectionPool, RedisStreamProducer
    redis = await RedisConnectionPool.get()
    app.state.producer = RedisStreamProducer(redis)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    resp = await client.post("/auth/token", json={"username": "testuser", "password": "pass"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestGateway:
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    async def test_get_token(self, client):
        resp = await client.post(
            "/auth/token",
            json={"username": "integtest", "password": "anypassword"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_submit_task_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "Test", "description": "Test description"},
        )
        assert resp.status_code == 401

    async def test_submit_task_success(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "title": "Integration Test Task",
                "description": "A task submitted from integration tests to verify the full API flow.",
                "priority": 5,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "accepted"
        assert "streaming_url" in data

    async def test_get_task_after_submit(self, client, auth_headers):
        submit_resp = await client.post(
            "/api/v1/tasks",
            json={"title": "Fetch Test", "description": "Task to test GET endpoint"},
            headers=auth_headers,
        )
        task_id = submit_resp.json()["task_id"]

        get_resp = await client.get(
            f"/api/v1/tasks/{task_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        task = get_resp.json()
        assert task["id"] == task_id
        assert task["title"] == "Fetch Test"
        assert task["status"] == "pending"

    async def test_list_tasks(self, client, auth_headers):
        resp = await client.get("/api/v1/tasks?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    async def test_get_nonexistent_task(self, client, auth_headers):
        resp = await client.get(
            "/api/v1/tasks/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_submit_task_validates_empty_title(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/tasks",
            json={"title": "", "description": "Valid description"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
