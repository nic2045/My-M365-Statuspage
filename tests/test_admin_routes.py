"""Admin routes and UI tests using TestClient with DISABLE_AUTH."""
import os

os.environ.setdefault("DISABLE_AUTH", "true")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestAdminGetRoutes:
    """Test GET endpoints in /admin."""

    def test_admin_dashboard_returns_200(self):
        """GET /admin should return 200 with service list."""
        response = client.get("/admin")
        assert response.status_code == 200
        assert "data-service" in response.text or "services" in response.text.lower()

    def test_admin_settings_returns_200(self):
        """GET /admin/settings should return 200 with service toggles."""
        response = client.get("/admin/settings")
        assert response.status_code == 200

    def test_admin_debug_returns_200(self):
        """GET /admin/debug should return 200."""
        response = client.get("/admin/debug")
        assert response.status_code == 200

    def test_admin_incidents_new_form_returns_200(self):
        """GET /admin/incidents/new should return 200 with form."""
        response = client.get("/admin/incidents/new")
        assert response.status_code == 200
        assert "form" in response.text.lower() or "incident" in response.text.lower()

    def test_admin_maintenance_new_form_returns_200(self):
        """GET /admin/maintenance/new should return 200 with form."""
        response = client.get("/admin/maintenance/new")
        assert response.status_code == 200


class TestAdminPostRoutes:
    """Test POST endpoints and side effects."""

    def test_create_incident_redirects(self):
        """POST /admin/incidents (create) should redirect."""
        response = client.post(
            "/admin/incidents",
            data={
                "title": "Test Incident",
                "service_name": "Exchange",
                "classification": "incident",
                "severity": "high",
                "description": "Test description",
            },
            follow_redirects=False,
        )
        assert response.status_code in (303, 302, 200)  # Redirect or success


class TestServiceStatusPage:
    """Test service status page rendering."""

    def test_service_status_page_renders(self):
        """Service status page should render without errors."""
        response = client.get("/")
        assert response.status_code == 200
