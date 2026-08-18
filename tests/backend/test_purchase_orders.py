"""
Tests for purchase order API endpoints.
"""
import copy

import pytest

import mock_data


@pytest.fixture
def restore_purchase_orders():
    """Restore the in-memory purchase_orders list after mutation tests.

    The app shares one module-level list across all tests, so slice-assign
    a snapshot back to keep tests independent.
    """
    snapshot = copy.deepcopy(mock_data.purchase_orders)
    yield
    mock_data.purchase_orders[:] = snapshot


def valid_po_payload(backlog_item_id="1"):
    """A valid create-PO request body for tests."""
    return {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "FilterMax Inc",
        "quantity": 350,
        "unit_cost": 5.5,
        "expected_delivery_date": "2025-10-15",
        "notes": "Expedite if possible",
    }


class TestPurchaseOrderEndpoints:
    """Test suite for purchase-order-related endpoints."""

    def test_create_purchase_order(self, client, restore_purchase_orders):
        """Test creating a purchase order for a backlog item."""
        response = client.post("/api/purchase-orders", json=valid_po_payload())
        assert response.status_code == 201

        po = response.json()
        assert po["backlog_item_id"] == "1"
        assert po["supplier_name"] == "FilterMax Inc"
        assert po["quantity"] == 350
        assert abs(po["unit_cost"] - 5.5) < 0.01
        assert po["status"] == "Pending"
        assert po["id"].startswith("PO-")
        assert "created_date" in po
        assert po["notes"] == "Expedite if possible"

    def test_get_purchase_order_by_backlog_item(self, client, restore_purchase_orders):
        """Test fetching the purchase order for a backlog item."""
        created = client.post("/api/purchase-orders", json=valid_po_payload()).json()

        response = client.get("/api/purchase-orders/1")
        assert response.status_code == 200

        po = response.json()
        assert po["id"] == created["id"]
        assert po["backlog_item_id"] == "1"

    def test_get_purchase_order_none_exists(self, client):
        """Test fetching a purchase order for a backlog item that has none."""
        response = client.get("/api/purchase-orders/2")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_create_purchase_order_unknown_backlog_item(self, client):
        """Test that an unknown backlog item is rejected."""
        response = client.post(
            "/api/purchase-orders", json=valid_po_payload(backlog_item_id="does-not-exist")
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_duplicate_purchase_order(self, client, restore_purchase_orders):
        """Test that a second PO for the same backlog item is rejected."""
        first = client.post("/api/purchase-orders", json=valid_po_payload())
        assert first.status_code == 201

        second = client.post("/api/purchase-orders", json=valid_po_payload())
        assert second.status_code == 400
        assert "already exists" in second.json()["detail"].lower()

    def test_create_purchase_order_invalid_quantity(self, client):
        """Test that zero/negative quantities are rejected."""
        payload = valid_po_payload()
        payload["quantity"] = 0
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 422

    def test_create_purchase_order_invalid_unit_cost(self, client):
        """Test that non-positive unit costs are rejected."""
        payload = valid_po_payload()
        payload["unit_cost"] = -1.5
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 422

    def test_backlog_reflects_purchase_order_flag(self, client, restore_purchase_orders):
        """Test that /api/backlog flags items that have a purchase order."""
        client.post("/api/purchase-orders", json=valid_po_payload())

        backlog = client.get("/api/backlog").json()
        by_id = {item["id"]: item for item in backlog}
        assert by_id["1"]["has_purchase_order"] is True
        assert by_id["2"]["has_purchase_order"] is False
