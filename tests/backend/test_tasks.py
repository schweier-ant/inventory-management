"""
Tests for tasks API endpoints.
"""
import copy

import pytest

import mock_data


@pytest.fixture
def restore_tasks():
    """Restore the in-memory tasks list after mutation tests.

    The app shares one module-level list across all tests, so slice-assign
    a snapshot back to keep tests independent.
    """
    snapshot = copy.deepcopy(mock_data.tasks)
    yield
    mock_data.tasks[:] = snapshot


class TestTasksEndpoints:
    """Test suite for tasks-related endpoints."""

    def test_get_all_tasks(self, client):
        """Test getting all tasks."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        first_task = data[0]
        assert "id" in first_task
        assert "title" in first_task
        assert "priority" in first_task
        assert "dueDate" in first_task
        assert "status" in first_task

    def test_task_field_types_and_values(self, client):
        """Test that task fields have valid types and constrained values."""
        response = client.get("/api/tasks")
        data = response.json()

        for task in data:
            assert isinstance(task["id"], int)
            assert isinstance(task["title"], str)
            assert task["priority"] in ["high", "medium", "low"]
            assert task["status"] in ["pending", "completed"]
            assert "2025-" in task["dueDate"] or "-" in task["dueDate"]

    def test_seeded_task_ids_avoid_client_mock_range(self, client):
        """Test that seeded task ids stay above the client-side mock ids (1-3)."""
        response = client.get("/api/tasks")
        data = response.json()

        for task in data:
            assert task["id"] > 100

    def test_create_task(self, client, restore_tasks):
        """Test creating a new task."""
        payload = {"title": "Audit reorder points", "priority": "medium", "dueDate": "2025-10-20"}
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 201

        task = response.json()
        assert task["title"] == payload["title"]
        assert task["priority"] == payload["priority"]
        assert task["dueDate"] == payload["dueDate"]
        assert task["status"] == "pending"
        assert isinstance(task["id"], int)

        # New task appears in the list
        all_tasks = client.get("/api/tasks").json()
        assert any(t["id"] == task["id"] for t in all_tasks)

    def test_task_ids_stay_unique_after_delete_and_create(self, client, restore_tasks):
        """Test that live task ids stay unique across deletes and creates."""
        first = client.post(
            "/api/tasks",
            json={"title": "First", "priority": "low", "dueDate": "2025-10-21"},
        ).json()
        client.delete(f"/api/tasks/{first['id']}")
        client.post(
            "/api/tasks",
            json={"title": "Second", "priority": "low", "dueDate": "2025-10-22"},
        )

        all_ids = [t["id"] for t in client.get("/api/tasks").json()]
        assert len(all_ids) == len(set(all_ids))

    def test_create_task_invalid_priority(self, client):
        """Test that an invalid priority is rejected."""
        payload = {"title": "Bad task", "priority": "urgent", "dueDate": "2025-10-20"}
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 422

    def test_create_task_empty_title(self, client):
        """Test that an empty title is rejected."""
        payload = {"title": "", "priority": "high", "dueDate": "2025-10-20"}
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 422

    def test_toggle_task(self, client, restore_tasks):
        """Test toggling a task between pending and completed."""
        task = client.post(
            "/api/tasks",
            json={"title": "Toggle me", "priority": "high", "dueDate": "2025-10-20"},
        ).json()

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/999999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_task(self, client, restore_tasks):
        """Test deleting a task."""
        task = client.post(
            "/api/tasks",
            json={"title": "Delete me", "priority": "low", "dueDate": "2025-10-20"},
        ).json()

        response = client.delete(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == task["id"]

        all_tasks = client.get("/api/tasks").json()
        assert not any(t["id"] == task["id"] for t in all_tasks)

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/999999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
