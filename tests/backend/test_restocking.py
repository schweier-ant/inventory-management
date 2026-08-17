"""
Tests for restocking API endpoints (recommendations and order submission).
"""
import re
from datetime import datetime

import pytest


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    # --- GET /api/restocking/recommendations ---

    def test_recommendations_respect_budget(self, client):
        """Test that the plan never exceeds the budget for various budgets."""
        for budget in [500, 3000, 5000, 12000]:
            response = client.get(f"/api/restocking/recommendations?budget={budget}")
            assert response.status_code == 200

            data = response.json()
            assert data["total_cost"] <= budget
            assert abs(data["remaining_budget"] - round(budget - data["total_cost"], 2)) < 0.01

            calculated_total = sum(item["line_cost"] for item in data["items"])
            assert abs(data["total_cost"] - calculated_total) < 0.01

    def test_recommendations_urgency_order(self, client):
        """Test greedy ordering: increasing trend first, then largest demand gap."""
        response = client.get("/api/restocking/recommendations?budget=12000")
        assert response.status_code == 200

        data = response.json()
        skus = [item["sku"] for item in data["items"]]
        # With everything affordable, order is fully determined by (trend, -gap)
        assert skus == ["MCU-402", "DRV-405", "PSU-501", "TMP-201",
                        "PRX-204", "PSU-506", "PCB-001"]

    def test_recommendations_exclude_negative_gap(self, client):
        """Test that items with falling demand are never recommended."""
        response = client.get("/api/restocking/recommendations?budget=100000")
        assert response.status_code == 200

        skus = [item["sku"] for item in response.json()["items"]]
        assert "STP-303" not in skus
        assert "SPR-602" not in skus

    def test_recommendations_partial_quantity(self, client):
        """Test partial fills when the budget covers only part of a gap."""
        # Budget 1000 covers the full first item (MCU-402: 150 x 6.50 = 975)
        response = client.get("/api/restocking/recommendations?budget=1000")
        data = response.json()
        assert data["items"][0]["sku"] == "MCU-402"
        assert data["items"][0]["recommended_quantity"] == 150

        # Budget 500 covers only floor(500 / 6.50) = 76 units
        response = client.get("/api/restocking/recommendations?budget=500")
        data = response.json()
        assert data["items"][0]["sku"] == "MCU-402"
        assert data["items"][0]["recommended_quantity"] == 76

    def test_recommendations_zero_budget(self, client):
        """Test that a zero budget returns an empty plan, not an error."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []
        assert data["total_cost"] == 0

    def test_recommendations_invalid_budget(self, client):
        """Test that negative or missing budget is rejected with 422."""
        response = client.get("/api/restocking/recommendations?budget=-5")
        assert response.status_code == 422

        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422

    def test_recommendations_item_structure(self, client):
        """Test that recommendation items have all fields the UI renders."""
        response = client.get("/api/restocking/recommendations?budget=12000")
        data = response.json()
        assert len(data["items"]) > 0

        for item in data["items"]:
            for field in ["sku", "name", "warehouse", "category", "trend",
                          "current_demand", "forecasted_demand", "demand_gap",
                          "unit_cost", "recommended_quantity", "line_cost",
                          "lead_time_days"]:
                assert field in item
            assert item["recommended_quantity"] > 0
            assert item["lead_time_days"] > 0
            assert abs(item["line_cost"] - item["recommended_quantity"] * item["unit_cost"]) < 0.01

    # --- POST /api/restocking/orders ---

    def test_create_restock_order(self, client):
        """Test that submitting a restock order creates a valid order."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "MCU-402", "quantity": 10}]},
        )
        assert response.status_code == 201

        created = response.json()
        assert len(created) == 1
        order = created[0]
        # Year in the order number must follow the creation date, not a literal
        assert re.match(rf"^RST-{datetime.now().year}-\d{{4}}$", order["order_number"])
        assert order["customer"] == "Internal Restocking"
        assert order["status"] == "Submitted"
        assert abs(order["total_value"] - 65.0) < 0.01
        item = order["items"][0]
        assert item["name"] == "32-bit ARM Microcontroller"
        assert item["quantity"] == 10
        assert isinstance(item["unit_price"], (int, float))

    def test_created_order_not_in_api_orders(self, client):
        """Test that restock orders stay out of /api/orders.

        Internal spend must not count as customer revenue in the dashboard,
        reports, and spending aggregates; the Orders page shows restock
        orders through /api/restocking/orders instead.
        """
        # Data is module-level state, so compare counts relatively
        count_before = len(client.get("/api/orders").json())

        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "PSU-501", "quantity": 4}]},
        )
        assert response.status_code == 201
        order_number = response.json()[0]["order_number"]

        all_orders = client.get("/api/orders").json()
        assert len(all_orders) == count_before
        assert order_number not in [o["order_number"] for o in all_orders]

    def test_duplicate_skus_merge_into_one_line_item(self, client):
        """Test that the same SKU twice in one request becomes one line item."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [
                {"sku": "MCU-402", "quantity": 1},
                {"sku": "MCU-402", "quantity": 2},
            ]},
        )
        assert response.status_code == 201

        created = response.json()
        assert len(created) == 1
        items = created[0]["items"]
        assert len(items) == 1
        assert items[0]["sku"] == "MCU-402"
        assert items[0]["quantity"] == 3

    def test_created_order_in_restocking_orders(self, client):
        """Test that GET /api/restocking/orders returns the order with lead time."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "PRX-204", "quantity": 2}]},
        )
        assert response.status_code == 201
        order_number = response.json()[0]["order_number"]

        restock_orders = client.get("/api/restocking/orders").json()
        match = [o for o in restock_orders if o["order_number"] == order_number]
        assert len(match) == 1
        assert "lead_time_days" in match[0]

    def test_one_order_per_warehouse_with_lead_times(self, client):
        """Test warehouse grouping and per-warehouse delivery lead times."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [
                {"sku": "MCU-402", "quantity": 1},   # San Francisco
                {"sku": "TMP-201", "quantity": 1},   # London
                {"sku": "PRX-204", "quantity": 1},   # Tokyo
            ]},
        )
        assert response.status_code == 201

        created = response.json()
        assert len(created) == 3

        expected_leads = {"San Francisco": 5, "London": 10, "Tokyo": 12}
        for order in created:
            lead = expected_leads[order["warehouse"]]
            assert order["lead_time_days"] == lead

            order_date = datetime.fromisoformat(order["order_date"])
            expected_delivery = datetime.fromisoformat(order["expected_delivery"])
            assert (expected_delivery - order_date).days == lead

    def test_post_unknown_sku(self, client):
        """Test that an unknown SKU is rejected with 400."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_post_invalid_payloads(self, client):
        """Test that zero quantity and empty item lists are rejected with 422."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "MCU-402", "quantity": 0}]},
        )
        assert response.status_code == 422

        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 422

    # --- Data consistency guard ---

    def test_forecast_skus_exist_in_inventory(self, client):
        """Test that every demand forecast SKU references a real inventory item."""
        forecasts = client.get("/api/demand").json()
        inventory_skus = {item["sku"] for item in client.get("/api/inventory").json()}

        for forecast in forecasts:
            assert forecast["item_sku"] in inventory_skus, \
                f"Forecast SKU {forecast['item_sku']} missing from inventory"
