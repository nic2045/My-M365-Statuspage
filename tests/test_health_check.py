import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoints:
    def test_health_liveness_200(self, client):
        """Liveness check should always return 200 with the fixed {"status": "ok"}
        contract that tests/test_docker_integration.py::test_health_200 relies on."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_readiness_200(self, client):
        """Readiness check should return 200 when DB is healthy."""
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] is True
        assert "timestamp" in data

    def test_health_full_200(self, client):
        """Full health check should return 200 when all systems healthy."""
        response = client.get("/api/v1/health/full")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"]["database"]["status"] == "up"
        assert "graph_api" in data["checks"]
        assert data["checks"]["timestamp"]
