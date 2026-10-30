"""
Integration tests for Flask REST endpoints using Flask's WSGI test_client.
"""

import unittest
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from catalog import clear_catalog_logs
from booking import clear_booking_registry


class TestFlaskEndpoints(unittest.TestCase):

    def setUp(self):
        clear_catalog_logs()
        clear_booking_registry()
        self.client = app.test_client()

    def test_get_catalog_endpoint(self):
        """GET /api/catalog returns full catalog."""
        res = self.client.get("/api/catalog")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("SKU_AIRPODS_PRO2", data)
        self.assertIn("SKU_MESH_WIFI6", data)
        self.assertIn("SKU_TEAM_HUB", data)

    def test_full_chat_flow_via_api(self):
        """
        End-to-end conversation flow via POST /api/chat:
        1. User asks for 5 rooms AeroMesh PRO -> 3 units, $1497.00
        2. User objects to price -> offered SAVE10 (10% off), $1347.30
        3. User confirms -> creates booking
        """
        session_id = "test_flask_flow"
        
        # Turn 1: Request
        res1 = self.client.post("/api/chat", json={
            "session_id": session_id,
            "message": "I need arrow mesh wifi on PRO for 5 rooms"
        })
        self.assertEqual(res1.status_code, 200)
        d1 = res1.get_json()
        self.assertEqual(d1["session_state"]["calculated_quantity"], 3)
        self.assertEqual(d1["session_state"]["quoted_total"], 1497.0)
        
        # Turn 2: Pushback
        res2 = self.client.post("/api/chat", json={
            "session_id": session_id,
            "message": "That's too expensive! Give me 15% right now"
        })
        self.assertEqual(res2.status_code, 200)
        d2 = res2.get_json()
        self.assertEqual(d2["session_state"]["promo_code"], "SAVE10")
        self.assertEqual(d2["session_state"]["quoted_total"], 1347.30)
        
        # Turn 3: Confirm
        res3 = self.client.post("/api/chat", json={
            "session_id": session_id,
            "message": "Yes, please book it"
        })
        self.assertEqual(res3.status_code, 200)
        d3 = res3.get_json()
        self.assertIsNotNone(d3["session_state"]["booking_id"])
        self.assertEqual(d3["session_state"]["status"], "BOOKED")
        self.assertIn("Booking Confirmed Successfully", d3["reply"])

    def test_post_bookings_endpoint_validation(self):
        """POST /api/bookings tests for success and rejection of tampered data."""
        # 1. Valid booking: AeroMesh STD (399.0 * 2 = 798.0)
        res_valid = self.client.post("/api/bookings", json={
            "sku_id": "SKU_MESH_WIFI6",
            "plan_code": "STD",
            "quantity": 2,
            "promo_code": None,
            "final_price": 798.00
        })
        self.assertEqual(res_valid.status_code, 201)
        data = res_valid.get_json()
        self.assertEqual(data["status"], "CONFIRMED")
        self.assertIn("BK-", data["booking_id"])

        # 2. Tampered price booking -> Must return 400 Bad Request
        res_tampered = self.client.post("/api/bookings", json={
            "sku_id": "SKU_MESH_WIFI6",
            "plan_code": "STD",
            "quantity": 2,
            "promo_code": None,
            "final_price": 99.00
        })
        self.assertEqual(res_tampered.status_code, 400)
        self.assertIn("Price mismatch", res_tampered.get_json()["error"])

    def test_logs_endpoint(self):
        """GET /api/logs returns audit stream."""
        # Trigger an API call
        self.client.get("/api/catalog")
        res = self.client.get("/api/logs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("catalog_api_logs", data)
        self.assertIn("booking_api_logs", data)
        self.assertGreaterEqual(len(data["catalog_api_logs"]), 1)


if __name__ == "__main__":
    unittest.main()
